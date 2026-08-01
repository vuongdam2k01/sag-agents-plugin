"""publish_one() — central orchestration (SPEC S9), shared by single-file publish
(sagw tool / CLI) and batch sync (each file in the batch calls back into this
same function — REVIEW-OPUS #10: sync must not have its own logic, it must
share publish_one() so there isn't a second behavior path during crash-recovery).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import assessment as assessment_mod
from . import audit, config, gate, gitutil, keys, manifest as manifest_mod
from . import manual, provenance, routing, state
from .restclient import SagApiError, SagClient

# The replace strategy is NOT YET FINAL — pending selftest S4 (BLOCKING, see docs/SPEC.md §S9).
# Safe-conservative default: delete-first (correct if DELETE is synchronous). If selftest
# confirms DELETE is async, change the SAGCTL_REPLACE_STRATEGY environment variable to
# "upload_then_delete" (or edit the default below after recording the result in SPEC.md).
DEFAULT_REPLACE_STRATEGY = os.environ.get("SAGCTL_REPLACE_STRATEGY", "delete_first")


class PublishError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass
class PublishResult:
    status: str  # pending | queued | skipped | dry-run | denied
    key: str = ""
    document_id: str | None = None
    route: str = ""
    reason: str = ""
    source_id: str = ""


def _client_from_credentials(profile: str = "default") -> SagClient:
    cred = config.Credentials(profile).require()
    return SagClient(base_url=cred["url"], token=cred["write_token"])


def find_existing_by_key(client: SagClient, source_id: str, key: str) -> dict | None:
    docs, suspected_truncated = client.list_documents_all(source_id)
    if suspected_truncated:
        raise PublishError(
            "PAGINATION_UNCERTAIN",
            f"list_documents for source {source_id} shows signs of being paginated/truncated — "
            f"dedupe cannot be trusted. Run `sagctl selftest --case pagination` "
            f"before publishing further.",
        )
    matches = [d for d in docs if d.get("filename") == key]
    if len(matches) > 1:
        raise PublishError(
            "MULTIPLE_MATCHES",
            f"found {len(matches)} documents with the same key '{key}' in source {source_id} "
            f"— needs manual human handling before publishing further (no blind auto-delete).",
        )
    return matches[0] if matches else None


def _replace_delete_first(client: SagClient, source_id: str, existing: dict) -> None:
    client.delete_document(source_id, existing["id"], tolerate_404=True)


def _replace_upload_then_delete(client: SagClient, source_id: str, existing: dict, upload_fn) -> dict:
    doc = upload_fn()
    client.delete_document(source_id, existing["id"], tolerate_404=True)
    return doc


def publish_one(
    file_path: Path,
    *,
    assessment: dict | None = None,
    manual_token: str | None = None,
    manual_args_str: str | None = None,
    agent: str = "unknown",
    trigger: str = "end-of-task",
    wait: bool = False,
    wait_timeout: float = 90.0,
    dry_run: bool = False,
    profile: str = "default",
) -> PublishResult:
    file_path = Path(file_path).resolve()
    if not file_path.is_file():
        raise PublishError("FILE_NOT_FOUND", str(file_path))

    m = manifest_mod.load_for(file_path)
    repo_root = manifest_mod.repo_root(m)
    in_git_repo = manifest_mod.git_root(m) is not None
    config.assert_no_repo_state_leak(repo_root)
    relpath = manifest_mod.relpath_of(file_path, m)
    key = keys.encode_key(relpath, m["key_format"])
    source_id = m["source_id"]

    manual_valid = False
    if manual_token is not None:
        if manual_args_str is None:
            raise PublishError("MANUAL_ARGS_MISSING", "manual_token provided but manual_args_str is missing")
        manual_valid = manual.consume(manual_token, manual_args_str)
        if not manual_valid:
            raise PublishError("INVALID_MANUAL_TOKEN", "manual token is invalid, expired, or has mismatched args")

    decision = routing.decide(
        relpath=relpath, manifest=m, assessment=assessment, manual_token_valid=manual_valid
    )

    if decision.route == routing.Route.REJECT_DENY:
        audit.append(source_id, {"event": "publish_denied", "key": key, "reason": decision.reason, "agent": agent})
        raise PublishError("DENIED_PATH", decision.reason)
    if decision.route == routing.Route.REJECT_NOT_INCLUDED:
        raise PublishError("NOT_INCLUDED", decision.reason)
    if decision.route == routing.Route.REJECT_NOT_KNOWLEDGE:
        audit.append(
            source_id,
            {"event": "publish_skipped", "key": key, "reason": decision.reason, "agent": agent, "assessment": assessment},
        )
        return PublishResult(status="skipped", key=key, route=decision.route, reason=decision.reason, source_id=source_id)
    if decision.route == routing.Route.QUEUE:
        from . import queue as queue_mod

        queue_mod.enqueue(
            source_id,
            path=str(file_path),
            key=key,
            relpath=relpath,
            assessment=assessment,
            reason=decision.reason,
            agent=agent,
        )
        return PublishResult(status="queued", key=key, route=decision.route, reason=decision.reason, source_id=source_id)

    # route in (AUTO, MANUAL) -> run the deterministic floor, then upload
    initiator = "user-manual" if decision.route == routing.Route.MANUAL else "agent-auto"

    floor = gate.check_floor(
        file_path=file_path, repo_root=repo_root, relpath=relpath, key=key, manifest=m,
        source_id=source_id, in_git_repo=in_git_repo,
    )
    if not floor.ok:
        if floor.code == "UNSCANNABLE" and decision.route == routing.Route.AUTO:
            # The engine could not read these bytes, so it will not certify them. That
            # is a reason for a human to look, not a reason the document cannot be
            # knowledge — banning the format would be the engine making the assessment's
            # decision for it.
            from . import queue as queue_mod

            queue_mod.enqueue(
                source_id, path=str(file_path), key=key, relpath=relpath,
                assessment=assessment, reason=f"not secret-scannable by the engine: {floor.reason}",
                agent=agent,
            )
            return PublishResult(
                status="queued", key=key, route=routing.Route.QUEUE,
                reason=floor.reason, source_id=source_id,
            )
        audit.append(
            source_id,
            {"event": "publish_rejected_floor", "key": key, "code": floor.code, "reason": floor.reason, "agent": agent},
        )
        raise PublishError(floor.code, floor.reason)

    blob = gitutil.hash_object(file_path)
    commit = gitutil.last_commit_touching(relpath, repo_root) if in_git_repo else None

    prov_record = {
        "sag_key": key,
        "sag_source_commit": commit,
        "sag_source_blob": blob,
        "sag_published_at": _now_iso(),
        "sag_status": "published",
        "sag_route": decision.route,
        "sag_in_git": in_git_repo,
        "sag_secret_scanned": floor.code != "UNSCANNABLE",
    }

    # Where provenance goes depends on the format, not on whether the document is
    # allowed to exist. Markdown carries it in-band (S3, survives SAG's parser per
    # S7); everything else — .pdf, .docx, .json, .csv — gets it in the state store,
    # which is where `maintain` looks when the parsed document has no frontmatter.
    if provenance.can_carry_frontmatter(file_path):
        upload_bytes = provenance.inject(
            file_path.read_text(encoding="utf-8"), prov_record
        ).encode("utf-8")
    else:
        upload_bytes = file_path.read_bytes()
    state.provenance_put(source_id, key, prov_record)

    full_assessment = None
    if assessment is not None:
        full_assessment = assessment_mod.enrich(
            assessment,
            initiator=initiator,
            trigger=trigger,
            agent=agent,
            key=key,
            path=relpath,
            source_id=source_id,
            commit=commit,
            criteria_available=[c["id"] for c in m.get("criteria", [])],
        )

    if dry_run:
        existing_preview = None
        try:
            client = _client_from_credentials(profile)
            existing_preview = find_existing_by_key(client, source_id, key)
        except (PublishError, SagApiError):
            pass
        return PublishResult(
            status="dry-run",
            key=key,
            route=decision.route,
            reason=f"would_replace={'yes' if existing_preview else 'no'}",
            source_id=source_id,
        )

    client = _client_from_credentials(profile)
    existing = find_existing_by_key(client, source_id, key)

    strategy = DEFAULT_REPLACE_STRATEGY
    if existing and strategy == "delete_first":
        _replace_delete_first(client, source_id, existing)
        doc = client.upload_document(source_id, key, upload_bytes)
    elif existing and strategy == "upload_then_delete":
        doc = _replace_upload_then_delete(
            client, source_id, existing, lambda: client.upload_document(source_id, key, upload_bytes)
        )
    else:
        doc = client.upload_document(source_id, key, upload_bytes)

    keys.assert_no_drift(key, doc.get("filename", ""))

    audit.append(
        source_id,
        {
            "event": "published",
            "key": key,
            "document_id": doc.get("id"),
            "route": decision.route,
            "initiator": initiator,
            "trigger": trigger,
            "agent": agent,
            "commit": commit,
            "blob": blob,
            "assessment": full_assessment,
            "replace_strategy": strategy if existing else None,
        },
    )
    audit.bump_cost_counter(source_id, key)

    if wait:
        doc = _wait_for_ready(client, source_id, doc["id"], timeout=wait_timeout)

    status = "pending"
    if wait:
        status = "ready" if doc.get("status") == "ready" and doc.get("chunk_count", 0) > 0 else "failed_or_empty"

    return PublishResult(status=status, key=key, document_id=doc.get("id"), route=decision.route, source_id=source_id)


def publish_content(
    relpath: str,
    text: str,
    *,
    assessment: dict | None = None,
    derived_from: list[str] | None = None,
    manifest_path: Path | None = None,
    manifest_name: str | None = None,
    agent: str = "unknown",
    trigger: str = "end-of-task",
    wait: bool = False,
    wait_timeout: float = 90.0,
    dry_run: bool = False,
    profile: str = "default",
) -> PublishResult:
    """Publish text the agent authored — no file, no repo required (SPEC A3).

    For a Hermes session synthesising a research note, or an agent distilling a PDF it
    just read with a document skill: the knowledge is real, but there is no commit —
    sometimes no file at all — to hang the old Git-only provenance model on.

    `relpath` is chosen by the caller (e.g. `research/2026-08-01-pricing-competitors.md`)
    and plays exactly the role a real file's relpath plays in `publish_one()`: it is what
    `include`/`exclude`/`deny_paths`/`ask_paths` match against, and what `key_format`
    encodes into the SAG key. Reusing that machinery means no new policy concepts and no
    new manifest fields — a document authored this way is governed by the exact same
    rules as a file, minus the clause that needs a commit.

    `derived_from` keeps the citation chain when this is a distillation: repo paths
    (ideally `path@blobsha`), URLs, or other SAG keys.

    The manifest is resolved without a file to walk up from: `manifest_path`,
    `manifest_name`, `$SAGCTL_MANIFEST`, then a walk up from the current working
    directory (which does not require that directory to be a Git repo — see
    `manifest.find_manifest()`), in that order (see `manifest.resolve()`).
    """
    m = manifest_mod.resolve(Path.cwd(), explicit=manifest_path, name=manifest_name)
    source_id = m["source_id"]
    key = keys.encode_key(relpath, m["key_format"])

    decision = routing.decide(
        relpath=relpath, manifest=m, assessment=assessment, manual_token_valid=False
    )

    if decision.route == routing.Route.REJECT_DENY:
        audit.append(source_id, {"event": "publish_denied", "key": key, "reason": decision.reason, "agent": agent})
        raise PublishError("DENIED_PATH", decision.reason)
    if decision.route == routing.Route.REJECT_NOT_INCLUDED:
        raise PublishError("NOT_INCLUDED", decision.reason)
    if decision.route == routing.Route.REJECT_NOT_KNOWLEDGE:
        audit.append(
            source_id,
            {"event": "publish_skipped", "key": key, "reason": decision.reason, "agent": agent, "assessment": assessment},
        )
        return PublishResult(status="skipped", key=key, route=decision.route, reason=decision.reason, source_id=source_id)
    if decision.route == routing.Route.QUEUE:
        from . import queue as queue_mod

        queue_mod.enqueue(
            source_id,
            path=f"authored:{relpath}",
            key=key,
            relpath=relpath,
            assessment=assessment,
            reason=decision.reason,
            agent=agent,
            content=text,
            derived_from=derived_from,
            manifest_path=m["_path"],
        )
        return PublishResult(status="queued", key=key, route=decision.route, reason=decision.reason, source_id=source_id)

    # route is AUTO (Mode B has no manual bypass — see publish_content's docstring
    # and SPEC A3: there is no file for a slash command to point a token at).
    floor = gate.check_floor_content(relpath=relpath, key=key, manifest=m, source_id=source_id, text=text)
    if not floor.ok:
        audit.append(
            source_id,
            {"event": "publish_rejected_floor", "key": key, "code": floor.code, "reason": floor.reason, "agent": agent},
        )
        raise PublishError(floor.code, floor.reason)

    prov_record = {
        "sag_key": key,
        "sag_source_commit": None,
        "sag_source_blob": None,
        "sag_derived_from": list(derived_from or []),
        "sag_published_at": _now_iso(),
        "sag_status": "published",
        "sag_route": decision.route,
        "sag_in_git": False,
        "sag_authored": True,
        "sag_secret_scanned": True,
    }

    if provenance.can_carry_frontmatter(Path(relpath)):
        upload_bytes = provenance.inject(text, prov_record).encode("utf-8")
    else:
        upload_bytes = text.encode("utf-8")
    state.provenance_put(source_id, key, prov_record)

    full_assessment = None
    if assessment is not None:
        full_assessment = assessment_mod.enrich(
            assessment,
            initiator="agent-auto",
            trigger=trigger,
            agent=agent,
            key=key,
            path=relpath,
            source_id=source_id,
            commit=None,
            criteria_available=[c["id"] for c in m.get("criteria", [])],
        )

    if dry_run:
        existing_preview = None
        try:
            client = _client_from_credentials(profile)
            existing_preview = find_existing_by_key(client, source_id, key)
        except (PublishError, SagApiError):
            pass
        return PublishResult(
            status="dry-run", key=key, route=decision.route,
            reason=f"would_replace={'yes' if existing_preview else 'no'}", source_id=source_id,
        )

    client = _client_from_credentials(profile)
    existing = find_existing_by_key(client, source_id, key)

    strategy = DEFAULT_REPLACE_STRATEGY
    if existing and strategy == "delete_first":
        _replace_delete_first(client, source_id, existing)
        doc = client.upload_document(source_id, key, upload_bytes)
    elif existing and strategy == "upload_then_delete":
        doc = _replace_upload_then_delete(
            client, source_id, existing, lambda: client.upload_document(source_id, key, upload_bytes)
        )
    else:
        doc = client.upload_document(source_id, key, upload_bytes)

    keys.assert_no_drift(key, doc.get("filename", ""))

    audit.append(
        source_id,
        {
            "event": "published",
            "key": key,
            "document_id": doc.get("id"),
            "route": decision.route,
            "initiator": "agent-auto",
            "trigger": trigger,
            "agent": agent,
            "commit": None,
            "blob": None,
            "derived_from": list(derived_from or []),
            "assessment": full_assessment,
            "replace_strategy": strategy if existing else None,
        },
    )
    audit.bump_cost_counter(source_id, key)

    if wait:
        doc = _wait_for_ready(client, source_id, doc["id"], timeout=wait_timeout)

    status = "pending"
    if wait:
        status = "ready" if doc.get("status") == "ready" and doc.get("chunk_count", 0) > 0 else "failed_or_empty"

    return PublishResult(status=status, key=key, document_id=doc.get("id"), route=decision.route, source_id=source_id)


def _wait_for_ready(client: SagClient, source_id: str, document_id: str, *, timeout: float) -> dict:
    """Opt-in polling, default timeout shorter than the Bash tool's hard timeout
    on common agent hosts (SPEC S9 / REVIEW-OPUS F26).

    Tolerates transient network errors (SagApiError status=0 — timeout/connection
    error, confirmed for real via selftest on sag.home/Tailscale: a GET request
    mid-poll can time out even though the server is healthy) — skip that attempt
    and keep polling until the deadline instead of letting one flaky network blip
    crash the whole publish. HTTPError/AuthError (status != 0, e.g. 401/404) are
    still raised immediately — those are real request errors, not a transient
    network issue.
    """
    deadline = time.monotonic() + timeout
    delay = 2.0
    doc = None
    while time.monotonic() < deadline:
        try:
            doc = client.get_document(source_id, document_id)
        except SagApiError as e:
            if e.status != 0:
                raise
            doc = doc or {}  # keep the previous result (if any) as the return value when the deadline expires
        else:
            if doc.get("status") in ("ready", "failed"):
                return doc
        time.sleep(min(delay, max(0.0, deadline - time.monotonic())))
        delay = min(delay * 1.5, 10.0)
    return doc or {}  # timeout -- caller decides the exit code (CLI uses exit 75)


def unpublish_one(source_id: str, key: str, *, reason: str, agent: str = "unknown", profile: str = "default") -> bool:
    client = _client_from_credentials(profile)
    doc = find_existing_by_key(client, source_id, key)
    if doc is None:
        raise PublishError("NOT_FOUND", f"no document found with key '{key}' in source {source_id}")
    ok = client.delete_document(source_id, doc["id"], tolerate_404=True)
    audit.append(
        source_id,
        {"event": "unpublished", "key": key, "document_id": doc["id"], "reason": reason, "agent": agent},
    )
    return ok


def reprocess_one(source_id: str, key: str, *, agent: str = "unknown", profile: str = "default") -> dict:
    client = _client_from_credentials(profile)
    doc = find_existing_by_key(client, source_id, key)
    if doc is None:
        raise PublishError("NOT_FOUND", f"no document found with key '{key}' in source {source_id}")
    job = client.reprocess_document(source_id, doc["id"])
    audit.append(source_id, {"event": "reprocessed", "key": key, "document_id": doc["id"], "job_id": job.get("id"), "agent": agent})
    return job


def publish_status(source_id: str, key: str, *, profile: str = "default") -> dict | None:
    client = _client_from_credentials(profile)
    return find_existing_by_key(client, source_id, key)


def _resolve_path(path: str) -> tuple[dict, str, str]:
    """Return (manifest, source_id, key) from a repo path — used by sagw
    (MCP write server) so the agent only needs to know the PATH, not SAG's
    internal source_id/key encoding."""
    p = Path(path).resolve()
    m = manifest_mod.load_for(p)
    relpath = manifest_mod.relpath_of(p, m)
    key = keys.encode_key(relpath, m["key_format"])
    return m, m["source_id"], key


def unpublish_by_path(path: str, *, reason: str, agent: str = "unknown", profile: str = "default") -> bool:
    _, source_id, key = _resolve_path(path)
    return unpublish_one(source_id, key, reason=reason, agent=agent, profile=profile)


def reprocess_by_path(path: str, *, agent: str = "unknown", profile: str = "default") -> dict:
    _, source_id, key = _resolve_path(path)
    return reprocess_one(source_id, key, agent=agent, profile=profile)


def status_by_path(path: str, *, profile: str = "default") -> dict | None:
    _, source_id, key = _resolve_path(path)
    return publish_status(source_id, key, profile=profile)


def publish_unreviewed(
    file_path: Path,
    *,
    reason: str,
    agent: str = "unknown",
    trigger: str = "user-command",
    profile: str = "default",
) -> PublishResult:
    """Path T1b (SPEC S8): bypasses `require` (no need to be merged/committed per
    the manifest threshold — the file just needs to exist), but does NOT bypass
    secret scan or deny_paths (S4 still applies — only the Git condition is
    relaxed). Keeps the key UNCHANGED (no filename change) — changing the
    filename would break reconcile later (REVIEW-OPUS F15)."""
    file_path = Path(file_path).resolve()
    if not file_path.is_file():
        raise PublishError("FILE_NOT_FOUND", str(file_path))
    m = manifest_mod.load_for(file_path)
    repo_root = manifest_mod.repo_root(m)
    config.assert_no_repo_state_leak(repo_root)
    relpath = manifest_mod.relpath_of(file_path, m)
    if routing.path_matches_any(relpath, m.get("deny_paths") or []):
        raise PublishError("DENIED_PATH", "deny_paths matched — blocks unreviewed too")
    key = keys.encode_key(relpath, m["key_format"])
    source_id = m["source_id"]

    secret_result = gate.check_secret_scan(file_path)
    if not secret_result.ok:
        raise PublishError(secret_result.code, secret_result.reason)

    cost_result = gate.check_cost_cap(source_id, m, key)
    if not cost_result.ok:
        raise PublishError(cost_result.code, cost_result.reason)

    in_git_repo = manifest_mod.git_root(m) is not None
    blob = gitutil.hash_object(file_path)
    commit = (gitutil.last_commit_touching(relpath, repo_root) or "UNCOMMITTED") if in_git_repo else None
    prov_record = {
        "sag_key": key,
        "sag_source_commit": commit,
        "sag_source_blob": blob,
        "sag_published_at": _now_iso(),
        "sag_status": "unreviewed",
        "sag_route": "unreviewed",
        "sag_in_git": in_git_repo,
    }
    if provenance.can_carry_frontmatter(file_path):
        upload_bytes = provenance.inject(
            file_path.read_text(encoding="utf-8"), prov_record
        ).encode("utf-8")
    else:
        upload_bytes = file_path.read_bytes()
    state.provenance_put(source_id, key, prov_record)

    client = _client_from_credentials(profile)
    existing = find_existing_by_key(client, source_id, key)
    if existing and DEFAULT_REPLACE_STRATEGY == "delete_first":
        _replace_delete_first(client, source_id, existing)
        doc = client.upload_document(source_id, key, upload_bytes)
    elif existing:
        doc = _replace_upload_then_delete(
            client, source_id, existing, lambda: client.upload_document(source_id, key, upload_bytes)
        )
    else:
        doc = client.upload_document(source_id, key, upload_bytes)
    keys.assert_no_drift(key, doc.get("filename", ""))

    audit.append(
        source_id,
        {
            "event": "published_unreviewed",
            "key": key,
            "document_id": doc.get("id"),
            "reason": reason,
            "agent": agent,
            "trigger": trigger,
            "commit": commit,
        },
    )
    audit.bump_cost_counter(source_id, key)
    return PublishResult(status="pending", key=key, document_id=doc.get("id"), route="unreviewed", reason=reason, source_id=source_id)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
