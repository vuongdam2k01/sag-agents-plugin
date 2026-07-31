"""16 verification cases against a real SAG instance (SPEC Phase P1). 7 BLOCKING
cases (S1, S4, S6, S7, S11, S12, S15) must run and produce results before the
default assumptions in publish.py/keys.py/restclient.py can be trusted. Run:

    sagctl selftest --url http://sag-host:8000 --token <TOKEN> [--case S1,S4,...]

Each case creates a temporary source/document, cleans up on a best-effort
basis afterward, and must NEVER be run against a source holding real
knowledge.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field

from .restclient import SagApiError, SagClient


def _poll_status(client: SagClient, source_id: str, doc_id: str, *, timeout: float, interval: float = 3.0) -> dict:
    """Poll get_document until ready/failed, tolerating transient network errors
    (SagApiError status=0) — a real observation on sag.home/Tailscale: a GET
    mid-poll can time out even though the server is healthy. Not catching it
    would crash the whole selftest case over one flaky network blip (this
    actually happened while running S14)."""
    deadline = time.monotonic() + timeout
    doc: dict = {}
    while time.monotonic() < deadline:
        try:
            doc = client.get_document(source_id, doc_id)
        except SagApiError as e:
            if e.status != 0:
                raise
            time.sleep(interval)
            continue
        if doc.get("status") in ("ready", "failed"):
            return doc
        time.sleep(interval)
    return doc


@dataclass
class CaseResult:
    case: str
    blocking: bool
    passed: bool | None  # None = cannot conclude automatically, a human needs to read detail
    detail: str
    decision_hint: str = ""


def _mk_source(client: SagClient, name: str) -> str:
    resp = client._request("POST", "/api/v1/sources", json_body={"name": name})
    return resp[1]["id"]


def _cleanup_source(client: SagClient, source_id: str) -> None:
    try:
        client._request("DELETE", f"/api/v1/sources/{source_id}")
    except SagApiError:
        pass


def case_s1_filename_roundtrip(client: SagClient) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s1")
    try:
        key = "docs/adr/probe.md"
        doc = client.upload_document(source_id, key, b"# probe\n\ntest content S1.\n")
        returned = doc.get("filename", "")
        passed = returned == key
        return CaseResult(
            "S1", True, passed,
            f"sent key='{key}', SAG returned filename='{returned}'",
            "key_format='path' if passed; if the server truncates to basename -> key_format='flat'",
        )
    finally:
        _cleanup_source(client, source_id)


def case_s2_key_roundtrip_variants(client: SagClient) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s2")
    try:
        variants = ["docs__adr__x.md", "docs/adr/日本語ファイル.md", "docs/adr/x y.md", "docs/adr/x#1.md"]
        results = {}
        for v in variants:
            try:
                doc = client.upload_document(source_id, v, b"probe s2\n")
                results[v] = doc.get("filename", "")
            except SagApiError as e:
                results[v] = f"ERROR {e.status}"
        return CaseResult("S2", False, None, json.dumps(results, ensure_ascii=False))
    finally:
        _cleanup_source(client, source_id)


def case_s3_duplicate_upload(client: SagClient) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s3")
    try:
        key = "docs/dup.md"
        d1 = client.upload_document(source_id, key, b"v1\n")
        d2 = client.upload_document(source_id, key, b"v2\n")
        docs, _ = client.list_documents_all(source_id)
        matches = [d for d in docs if d.get("filename") == key]
        return CaseResult(
            "S3", False, None,
            f"uploaded twice with the same key -> {len(matches)} document(s) (id1={d1.get('id')}, id2={d2.get('id')})",
        )
    finally:
        _cleanup_source(client, source_id)


def case_s4_delete_semantics(client: SagClient, *, ready_timeout: float = 300.0) -> CaseResult:
    """Uses direct GET-by-id (404 or not) as evidence — does NOT use `search`:
    confirmed on sag.home that semantic search can fail to find a chunk even
    though it genuinely exists (a meaningless marker carries no semantic
    signal), causing a false negative. GET-by-id is a binary, unambiguous
    signal."""
    source_id = _mk_source(client, "sagctl-selftest-s4")
    try:
        key = "docs/delete-probe.md"
        doc = client.upload_document(source_id, key, b"# delete probe\n\ns4 content\n")
        doc_id = doc["id"]
        if doc.get("status") not in ("ready", "failed"):
            doc = _poll_status(client, source_id, doc_id, timeout=ready_timeout)
        status = doc.get("status")
        if status != "ready":
            return CaseResult("S4", True, None, f"document not ready within {ready_timeout}s (status={status}) -- cannot verify DELETE")

        client.delete_document(source_id, doc_id, tolerate_404=False)

        observations = []
        for t in (0, 5, 30):
            if t > 0:
                time.sleep(t)
            try:
                client.get_document(source_id, doc_id)
                still_exists = True
            except SagApiError as e:
                still_exists = not (e.status == 404)
            observations.append((t, still_exists))

        async_delete = any(exists for _, exists in observations)
        return CaseResult(
            "S4", True, not async_delete,
            f"GET-by-id after delete (seconds, still exists?): {observations}",
            "SYNCHRONOUS DELETE -> keep SAGCTL_REPLACE_STRATEGY=delete_first (default). "
            "ASYNC DELETE (still exists at t>0) -> switch to upload_then_delete and update docs/SPEC.md §S9.",
        )
    finally:
        _cleanup_source(client, source_id)


def case_s5_delete_then_reupload(client: SagClient) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s5")
    try:
        key = "docs/race.md"
        d1 = client.upload_document(source_id, key, b"v1\n")
        client.delete_document(source_id, d1["id"], tolerate_404=False)
        d2 = client.upload_document(source_id, key, b"v2\n")
        return CaseResult("S5", False, None, f"delete({d1['id']}) then re-upload -> new id {d2['id']}, status={d2.get('status')}")
    finally:
        _cleanup_source(client, source_id)


def case_s6_pagination(client: SagClient, *, n: int = 120) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s6")
    try:
        for i in range(n):
            client.upload_document(source_id, f"docs/page-probe-{i:04d}.md", f"probe {i}\n".encode())
        docs, truncated = client.list_documents_all(source_id)
        passed = len(docs) == n and not truncated
        return CaseResult(
            "S6", True, passed,
            f"uploaded {n} documents, list_documents_all returned {len(docs)}, suspected_truncated={truncated}",
            "if passed: pagination (if any) is handled correctly. if not: check "
            "restclient.list_documents_all and SAG's actual limit/offset parameters.",
        )
    finally:
        _cleanup_source(client, source_id)


def case_s7_frontmatter_banner_in_chunk(client: SagClient, *, ready_timeout: float = 300.0) -> CaseResult:
    """Uses GET /documents/{id}/parsed (the real, verbatim parsed content) to
    check whether the banner survives the parser — does NOT use `search`:
    semantic search can miss a meaningless marker string even though the
    content is intact (confirmed on sag.home: the pre-delete search in S4 also
    missed it despite the document genuinely existing). `/parsed` is direct,
    unambiguous evidence."""
    from . import provenance

    source_id = _mk_source(client, "sagctl-selftest-s7")
    try:
        text = provenance.inject(
            "# Heading 1\n\ncontent 1 unique_marker_s7_body\n\n## Heading 2\n\ncontent 2\n",
            {"sag_key": "docs/probe.md", "sag_status": "published"},
        )
        banner = "\n> [SUPERSEDED by ADR-0099] unique_marker_s7_banner\n"
        text = text.replace("## Heading 2", "## Heading 2" + banner)
        doc = client.upload_document(source_id, "docs/probe.md", text.encode("utf-8"))
        doc_id = doc["id"]
        if doc.get("status") not in ("ready", "failed"):
            doc = _poll_status(client, source_id, doc_id, timeout=ready_timeout)
        status = doc.get("status")
        if status != "ready":
            return CaseResult("S7", True, None, f"document not ready (status={status})")
        parsed = client.get_document_parsed(source_id, doc_id)
        found = "unique_marker_s7_banner" in parsed
        return CaseResult(
            "S7", True, found,
            f"banner marker present in /parsed after ready -> found={found}",
            "found=True -> the banner survives the parser, the superseded approach (keep key + banner) is viable. "
            "found=False -> the banner is stripped, a different approach is needed for superseded.",
        )
    finally:
        _cleanup_source(client, source_id)


def case_s8_ready_but_empty(client: SagClient, *, ready_timeout: float = 120.0) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s8")
    try:
        doc = client.upload_document(source_id, "docs/empty.md", b"---\ntitle: only frontmatter\n---\n")
        doc_id = doc["id"]
        if doc.get("status") not in ("ready", "failed"):
            doc = _poll_status(client, source_id, doc_id, timeout=ready_timeout)
        status = doc.get("status")
        chunk_count = doc.get("chunk_count", -1)
        return CaseResult("S8", False, None, f"status={status}, chunk_count={chunk_count}")
    finally:
        _cleanup_source(client, source_id)


def case_s9_reprocess_ids(client: SagClient, *, ready_timeout: float = 300.0) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s9")
    try:
        doc = client.upload_document(source_id, "docs/reprocess-probe.md", b"# probe\n\nunique_marker_s9\n")
        doc_id = doc["id"]
        if doc.get("status") not in ("ready", "failed"):
            doc = _poll_status(client, source_id, doc_id, timeout=ready_timeout)
        job = client.reprocess_document(source_id, doc_id)
        time.sleep(5)
        doc_after = client.get_document(source_id, doc_id)
        return CaseResult(
            "S9", False, None,
            f"document_id before={doc_id}, after reprocess={doc_after.get('id')}, job={job.get('id')}",
        )
    finally:
        _cleanup_source(client, source_id)


def case_s10_ingest_title(client: SagClient) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s10")
    try:
        doc = client.ingest_text(source_id, text="s10 ingest content", title="my-title-s10")
        return CaseResult("S10", False, None, f"ingest title='my-title-s10' -> filename='{doc.get('filename')}'")
    finally:
        _cleanup_source(client, source_id)


def case_s11_multi_identity(client_a: SagClient, client_b: SagClient) -> CaseResult:
    source_a = _mk_source(client_a, "sagctl-selftest-s11-a")
    try:
        client_a.upload_document(source_a, "docs/only-a.md", b"only user A wrote this\n")
        try:
            sources_b = client_b.list_sources()
            visible = any(s.get("id") == source_a for s in sources_b)
        except SagApiError:
            visible = False
        return CaseResult(
            "S11", True, not visible,
            f"can user B's list_sources() see user A's source? visible={visible}",
            "visible=False -> multi-identity IS isolated, per-agent tokens provide real isolation. "
            "visible=True -> NOT isolated, downgrade per-agent identity to attribution/revocation only "
            "(and S12/S13 decide whether attribution/revocation is real).",
        )
    finally:
        _cleanup_source(client_a, source_a)


def _decode_jwt_payload(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None


def case_s12_token_lifecycle(client: SagClient) -> CaseResult:
    claims = _decode_jwt_payload(client.token)
    has_exp = bool(claims and "exp" in claims)
    detail = f"JWT claims decode: {claims if claims else 'could not decode (not a standard 3-part JWT?)'}"
    return CaseResult(
        "S12", True, None,
        detail + f" | has_exp={has_exp}",
        "has_exp=False -> the token doesn't self-expire, revocation must rely on another mechanism "
        "(manually check the logout/revoke endpoint via /docs OpenAPI). Record the result in SPEC.md S12/R3.",
    )


def case_s13_server_attribution(client_a: SagClient, client_b: SagClient) -> CaseResult:
    source_id = _mk_source(client_a, "sagctl-selftest-s13")
    try:
        doc = client_a.upload_document(source_id, "docs/attrib.md", b"probe s13\n")
        full = client_a.get_document(source_id, doc["id"])
        has_owner_field = any(k in full for k in ("owner", "created_by", "uploaded_by", "user_id"))
        return CaseResult(
            "S13", False, None,
            f"DocumentOut fields: {sorted(full.keys())}, has_owner_field={has_owner_field}",
            "has_owner_field=False -> drop the server-side 'attribution' claim from R3, leaving only local attribution (audit.py, unverified).",
        )
    finally:
        _cleanup_source(client_a, source_id)


def case_s14_limits(client: SagClient) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s14")
    try:
        t0 = time.monotonic()
        big = ("x" * 500_000).encode()
        try:
            doc = client.upload_document(source_id, "docs/big.md", b"# big\n\n" + big)
            big_ok = True
        except SagApiError as e:
            big_ok = False
            doc = None
        t_upload = time.monotonic() - t0
        detail = f"upload 500KB: ok={big_ok}, upload_time={t_upload:.1f}s"
        if doc:
            t1 = time.monotonic()
            if doc.get("status") not in ("ready", "failed"):
                doc = _poll_status(client, source_id, doc["id"], timeout=300.0)
            status = doc.get("status")
            detail += f", time_to_{status}={time.monotonic()-t1:.1f}s"
        return CaseResult("S14", False, None, detail)
    finally:
        _cleanup_source(client, source_id)


def case_s15_rest_mcp_consistency(client: SagClient) -> CaseResult:
    source_id = _mk_source(client, "sagctl-selftest-s15")
    try:
        key = "docs/rest-mcp-check.md"
        client.upload_document(source_id, key, b"unique_marker_s15\n")
        return CaseResult(
            "S15", True, None,
            f"uploaded via REST with key='{key}' into source_id='{source_id}'. "
            f"MANDATORY MANUAL STEP: use an MCP client (Claude Code/Inspector) to call "
            f"list_documents(source_id='{source_id}') via the 'sag' server and confirm the returned "
            f"filename equals '{key}'.",
            "matches -> path-based citation resolves correctly via MCP. mismatch -> must investigate "
            "encoding differences between SAG's REST path (sagctl) and MCP path (sag).",
        )
    finally:
        _cleanup_source(client, source_id)


def case_s16_grep_exact_scoped(client: SagClient) -> CaseResult:
    return CaseResult(
        "S16", False, None,
        "grep is an MCP tool (not present in the REST client) — check manually via MCP: "
        "does grep('unique_rare_identifier') in source A return a result, "
        "and does the same grep leak into source B (checking scope).",
    )


ALL_CASES = {
    "S1": case_s1_filename_roundtrip,
    "S2": case_s2_key_roundtrip_variants,
    "S3": case_s3_duplicate_upload,
    "S4": case_s4_delete_semantics,
    "S5": case_s5_delete_then_reupload,
    "S6": case_s6_pagination,
    "S7": case_s7_frontmatter_banner_in_chunk,
    "S8": case_s8_ready_but_empty,
    "S9": case_s9_reprocess_ids,
    "S10": case_s10_ingest_title,
    "S12": case_s12_token_lifecycle,
    "S14": case_s14_limits,
    "S15": case_s15_rest_mcp_consistency,
    "S16": case_s16_grep_exact_scoped,
}
NEEDS_SECOND_IDENTITY = {"S11": case_s11_multi_identity, "S13": case_s13_server_attribution}

BLOCKING = {"S1", "S4", "S6", "S7", "S11", "S12", "S15"}


def run_cases(client: SagClient, case_ids: list[str], client_b: SagClient | None = None) -> list[CaseResult]:
    results = []
    for cid in case_ids:
        if cid in ALL_CASES:
            results.append(ALL_CASES[cid](client))
        elif cid in NEEDS_SECOND_IDENTITY:
            if client_b is None:
                results.append(CaseResult(cid, True, None, "--token-b (second identity) is required to run this case"))
            else:
                results.append(NEEDS_SECOND_IDENTITY[cid](client, client_b))
        else:
            results.append(CaseResult(cid, False, None, f"case does not exist: {cid}"))
    return results
