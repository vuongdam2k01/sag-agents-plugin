"""SAG REST API client — stdlib only (urllib), never touches SAG's source.

Talks to SAG exactly like its own frontend does: calls the public REST
endpoints (`/api/v1/...`) verified in docs/DESIGN.md section 1.1. Does not
install, patch, or add routes to SAG — this client is just an HTTP caller.

Pagination of `GET .../documents` is NOT YET confirmed (selftest S6,
BLOCKING) — the `list_documents_all` function proactively paginates as a
precaution and warns if the returned count looks suspiciously round, as if
pagination is being silently truncated without the API declaring limit/offset explicitly.
"""
from __future__ import annotations

import json
import mimetypes
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class SagApiError(RuntimeError):
    def __init__(self, status: int, body: dict | str, method: str, path: str):
        self.status = status
        self.body = body
        super().__init__(f"SAG API {method} {path} -> HTTP {status}: {body}")


class SagAuthError(SagApiError):
    pass


@dataclass
class SagClient:
    base_url: str
    token: str
    timeout: float = 30.0

    def __post_init__(self):
        self.base_url = self.base_url.rstrip("/")

    # -- low-level -----------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        raw_body: bytes | None = None,
        extra_headers: dict | None = None,
        timeout: float | None = None,
    ):
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        if extra_headers:
            headers.update(extra_headers)
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif raw_body is not None:
            body = raw_body
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
                parsed = json.loads(raw) if raw else None
                return resp.status, parsed
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                parsed = raw.decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise SagAuthError(e.code, parsed, method, path) from None
            raise SagApiError(e.code, parsed, method, path) from None
        except urllib.error.URLError as e:
            raise SagApiError(0, str(e.reason), method, path) from None
        except TimeoutError as e:
            # A socket-level timeout while reading the response is NOT always
            # wrapped into a URLError by urllib (observed for real on sag.home
            # over Tailscale — a raw TimeoutError leaks out of
            # http.client.getresponse()). Not wrapping it = the entire polling
            # loop (publish --wait, selftest) crashes over one transient
            # network hiccup. Wrap it into SagApiError for consistency with
            # every other network error; the caller decides whether to retry.
            raise SagApiError(0, f"timeout: {e}", method, path) from None
        except ConnectionError as e:
            raise SagApiError(0, f"connection error: {e}", method, path) from None

    def _request_raw_text(self, method: str, path: str, *, timeout: float | None = None) -> str:
        """Like `_request` but does NOT parse JSON — used for endpoints that
        return plain text (e.g. `/documents/{id}/parsed`, `/documents/{id}/file`).
        Confirmed via selftest S7 on sag.home: these endpoints return raw
        markdown, not JSON-wrapped — `_request` would normally crash at `json.loads`."""
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        req = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise SagAuthError(e.code, body, method, path) from None
            raise SagApiError(e.code, body, method, path) from None
        except urllib.error.URLError as e:
            raise SagApiError(0, str(e.reason), method, path) from None
        except TimeoutError as e:
            raise SagApiError(0, f"timeout: {e}", method, path) from None
        except ConnectionError as e:
            raise SagApiError(0, f"connection error: {e}", method, path) from None

    # -- auth -----------------------------------------------------------

    def login(self, name: str, email: str | None = None, password: str | None = None) -> dict:
        body = {"name": name}
        if email is not None:
            body["email"] = email
        if password is not None:
            body["password"] = password
        _, data = self._request("POST", "/api/v1/auth/login", json_body=body)
        return data

    def whoami(self) -> dict:
        _, data = self._request("GET", "/api/v1/auth/me")
        return data

    def capabilities(self) -> dict:
        """`GET /system/capabilities` — needs no token (confirmed by selftest on
        sag.home: max_upload_mb, supported formats, default search_strategy). Used
        by `sagctl setup probe` to describe an instance before anything is
        provisioned against it."""
        _, data = self._request("GET", "/api/v1/system/capabilities")
        return data or {}

    def health(self) -> dict:
        _, data = self._request("GET", "/api/v1/system/health")
        return data

    # -- sources ----------------------------------------------------------

    def list_sources(self) -> list[dict]:
        _, data = self._request("GET", "/api/v1/sources")
        return data or []

    def get_source(self, source_id: str) -> dict:
        _, data = self._request("GET", f"/api/v1/sources/{urllib.parse.quote(source_id)}")
        return data

    def create_source(self, name: str, **extra) -> dict:
        _, data = self._request("POST", "/api/v1/sources", json_body={"name": name, **extra})
        return data

    def update_source(self, source_id: str, **fields) -> dict:
        _, data = self._request("PATCH", f"/api/v1/sources/{urllib.parse.quote(source_id)}", json_body=fields)
        return data

    def delete_source(self, source_id: str) -> None:
        self._request("DELETE", f"/api/v1/sources/{urllib.parse.quote(source_id)}")

    # -- documents --------------------------------------------------------

    def list_documents(self, source_id: str, *, limit: int | None = None, offset: int | None = None) -> list[dict]:
        path = f"/api/v1/sources/{urllib.parse.quote(source_id)}/documents"
        if limit is not None or offset is not None:
            qs = {}
            if limit is not None:
                qs["limit"] = limit
            if offset is not None:
                qs["offset"] = offset
            path += "?" + urllib.parse.urlencode(qs)
        _, data = self._request("GET", path)
        return data or []

    def list_documents_all(self, source_id: str, *, page_size: int = 100, max_pages: int = 200) -> tuple[list[dict], bool]:
        """Paginates defensively. Returns (docs, suspected_truncated).

        Confirmed by selftest S6 on sag.home (2026-07-31): SAG **completely
        ignores** `limit`/`offset` — calling with `limit=2` on a source with 5
        documents still returns all 5 (direct evidence: `len(first) > page_size`
        actually happens when testing with 120 documents + page_size=100).
        The first version of this heuristic treated "page 2 repeats page 1" as
        a sign of TRUNCATION — wrong: that is only a sign the server does not
        respect limit/offset, and since the FIRST call already returned every
        document (not limited by `limit`), nothing is actually missing. Fix:
        if `len(first) >= page_size` is because the server ignores `limit`,
        that's not truncation — only when page 2 contains NEW ids (the server
        actually respects offset) does it need to keep merging.
        """
        first = self.list_documents(source_id, limit=page_size, offset=0)
        if len(first) > page_size:
            # server returned more than the limit sent -> direct evidence it
            # ignores limit entirely -> we already have everything from this one call.
            return first, False
        if len(first) < page_size:
            return first, False

        # len(first) == page_size exactly hits the boundary -> one call alone
        # can't distinguish "exactly matches the total" from "got truncated" -> try page 2.
        second = self.list_documents(source_id, limit=page_size, offset=page_size)
        first_ids = {d.get("id") for d in first}
        if not second:
            return first, False
        second_ids = {d.get("id") for d in second}
        if second_ids <= first_ids:
            # page 2 has nothing new -> server ignores offset, but page 1
            # (exactly page_size) was already everything, nothing is missing.
            return first, False

        all_docs = list(first) + list(second)
        seen_ids = first_ids | second_ids
        offset = page_size * 2
        for _ in range(max_pages):
            page = self.list_documents(source_id, limit=page_size, offset=offset)
            if not page:
                return all_docs, False
            page_ids = {d.get("id") for d in page}
            if page_ids <= seen_ids:
                # can't make further progress even though offset was respected
                # on prior pages -> stop, unsure whether anything is still missing -> report suspected.
                return all_docs, True
            all_docs.extend(page)
            seen_ids |= page_ids
            if len(page) < page_size:
                return all_docs, False
            offset += page_size
        return all_docs, True  # exceeded max_pages -> suspected, let the caller verify

    def get_document(self, source_id: str, document_id: str) -> dict:
        _, data = self._request(
            "GET", f"/api/v1/sources/{urllib.parse.quote(source_id)}/documents/{urllib.parse.quote(document_id)}"
        )
        return data

    def get_document_parsed(self, source_id: str, document_id: str) -> str:
        """The PARSED markdown content (including frontmatter, the banner we
        inject at publish time) — confirmed via selftest S7: this is where
        `content` lives, NOT `get_document()` (DocumentOut has no content/text
        field — confirmed via selftest S13, the full field list has no content)."""
        return self._request_raw_text(
            "GET",
            f"/api/v1/sources/{urllib.parse.quote(source_id)}/documents/{urllib.parse.quote(document_id)}/parsed",
        )

    def upload_document(self, source_id: str, filename: str, content: bytes) -> dict:
        boundary = f"----sagctl{secrets.token_hex(16)}"
        content_type = mimetypes.guess_type(filename)[0] or "text/markdown"
        parts = [
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            content,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
        body = b"".join(p if isinstance(p, bytes) else p.encode("utf-8") for p in parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        _, data = self._request(
            "POST",
            f"/api/v1/sources/{urllib.parse.quote(source_id)}/documents",
            raw_body=body,
            extra_headers=headers,
        )
        return data

    def ingest_text(self, source_id: str, *, text: str | None = None, messages: list[dict] | None = None, title: str | None = None) -> dict:
        body: dict = {}
        if text is not None:
            body["text"] = text
        if messages is not None:
            body["messages"] = messages
        if title is not None:
            body["title"] = title
        _, data = self._request(
            "POST", f"/api/v1/sources/{urllib.parse.quote(source_id)}/documents/ingest", json_body=body
        )
        return data

    def reprocess_document(self, source_id: str, document_id: str) -> dict:
        _, data = self._request(
            "POST",
            f"/api/v1/sources/{urllib.parse.quote(source_id)}/documents/{urllib.parse.quote(document_id)}/reprocess",
        )
        return data

    def delete_document(self, source_id: str, document_id: str, *, tolerate_404: bool = True) -> bool:
        try:
            self._request(
                "DELETE",
                f"/api/v1/sources/{urllib.parse.quote(source_id)}/documents/{urllib.parse.quote(document_id)}",
            )
            return True
        except SagApiError as e:
            if tolerate_404 and e.status == 404:
                return True  # already gone -> treat as success (crash-recovery, REVIEW-OPUS #10)
            raise

    # -- jobs ---------------------------------------------------------------

    def get_job(self, job_id: str) -> dict:
        _, data = self._request("GET", f"/api/v1/jobs/{urllib.parse.quote(job_id)}")
        return data

    # -- search ---------------------------------------------------------------

    def search(self, query: str, *, source_id: str | None = None, strategy: str = "vector", top_k: int = 10) -> dict:
        body = {"query": query, "strategy": strategy, "top_k": top_k}
        if source_id:
            path = f"/api/v1/sources/{urllib.parse.quote(source_id)}/search"
        else:
            path = "/api/v1/search"
        _, data = self._request("POST", path, json_body=body)
        return data
