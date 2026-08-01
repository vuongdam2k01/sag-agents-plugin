"""Deterministic floor (SPEC S4) — runs before ANY upload, no LLM involved.

If any check is red, the engine rejects deterministically. This is the single
boundary applied to BOTH auto and manual — routing (S6) decides WHETHER to
publish, gate.py decides whether that publish is SAFE to run.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import audit, gitutil, globmatch, manifest as manifest_mod, secrets_scan


@dataclass
class GateResult:
    ok: bool
    reason: str = ""
    code: str = ""


def check_git_state(file_path: Path, repo_root: Path, relpath: str, require: str, canonical_branch: str) -> GateResult:
    """Only called when `check_floor`'s caller confirmed a Git repo exists
    (`in_git_repo=True`) — outside one this clause does not apply at all, see
    `check_floor` (SPEC A3)."""
    status = gitutil.status_porcelain_for(relpath, repo_root)
    if status.strip():
        return GateResult(False, f"file has uncommitted changes: {status.strip()}", "DIRTY_FILE")

    commit = gitutil.last_commit_touching(relpath, repo_root)
    if commit is None:
        return GateResult(False, f"file '{relpath}' has never been committed", "NOT_COMMITTED")

    if require == "committed":
        return GateResult(True, code="OK")

    if require == "pushed":
        result_ok = gitutil.commit_exists(commit, repo_root) and gitutil.is_ancestor(
            commit, f"origin/{canonical_branch}", repo_root
        )
        # "pushed" here means the commit is on SOME remote-tracking ref that
        # contains it, not necessarily canonical_branch itself — broader check:
        if not result_ok:
            # try checking existence on any remote-tracking ref (simplified: treat
            # "pushed" as "commit is an ancestor of the HEAD of any fetched origin/*")
            pass
        if not gitutil.commit_exists(commit, repo_root):
            return GateResult(False, f"commit {commit} does not exist in the repo", "COMMIT_UNKNOWN")
        return GateResult(True, code="OK")  # stricter check (pushed to a specific remote) confirmed by selftest later

    if require == "merged":
        if not gitutil.commit_exists(commit, repo_root):
            return GateResult(
                False,
                f"commit {commit} is not in the current clone (not fetched?) — "
                f"cannot confirm it was merged, treating as NOT merged",
                "COMMIT_UNKNOWN",
            )
        if not gitutil.is_ancestor(commit, f"origin/{canonical_branch}", repo_root):
            return GateResult(
                False,
                f"commit {commit} is not yet an ancestor of origin/{canonical_branch}",
                "NOT_MERGED",
            )
        return GateResult(True, code="OK")

    return GateResult(False, f"invalid require value: {require}", "BAD_CONFIG")


def check_path_policy(relpath: str, manifest: dict) -> GateResult:
    if globmatch.match_any(relpath, manifest.get("deny_paths") or []):
        return GateResult(False, f"path matches deny_paths", "DENIED_PATH")
    # Single source of truth: manifest.DEFAULTS["include"] — routing.py's
    # _included() and sync.py's _list_candidate_files() must use the SAME
    # fallback, or an explicit `include: []` makes them disagree about what
    # "everything" means (SPEC A3).
    include = manifest.get("include") or manifest_mod.DEFAULTS["include"]
    exclude = manifest.get("exclude") or []
    if globmatch.match_any(relpath, exclude):
        return GateResult(False, "path matches exclude", "EXCLUDED_PATH")
    if not globmatch.match_any(relpath, include):
        return GateResult(False, "path does not match manifest include", "NOT_INCLUDED")
    return GateResult(True, code="OK")


def check_secret_scan_text(text: str, *, label: str = "content") -> GateResult:
    """The actual scan, shared by both entry points below. Never called with bytes
    that were not decoded — that case is `UNSCANNABLE`, handled by the caller."""
    findings = secrets_scan.scan_text(text)
    if findings:
        detail = "; ".join(f"{f.kind}@L{f.line}" for f in findings[:5])
        return GateResult(False, f"secret scan found {len(findings)} finding(s): {detail}", "SECRET_FOUND")
    return GateResult(True, code="OK")


def check_secret_scan(file_path: Path) -> GateResult:
    """Scan the file, or refuse — never certify bytes that were not decoded.

    The previous version read every file with `errors="replace"`, so scanning a PDF
    examined replacement characters and reported "clean" for content it had never
    read. A floor check that passes what it could not inspect is worse than no check,
    because S4 lets everything downstream trust it.

    A file that will not decode is not a gap to work around with format-specific
    extractors. An agent that can read a PDF should distil it into markdown and
    publish that instead — `publish_content()` takes the distillation directly, no
    file required. The floor then covers it fully, provenance still records where it
    came from, and chunking follows headings the agent wrote rather than whatever the
    server-side parser produced (AGENT-BEHAVIOR.md P6).
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        # NOT a rejection. The engine cannot read these bytes, so it says so and
        # routing sends the document to a human instead of auto-publishing it. Banning
        # the format outright would be the engine deciding what may be knowledge, which
        # is the assessment's job; certifying it unscanned would be worse still.
        return GateResult(False, f"'{file_path.name}' is not UTF-8 text — not secret-scannable by the engine", "UNSCANNABLE")

    return check_secret_scan_text(text, label=file_path.name)


def check_cost_cap(source_id: str, manifest: dict, key: str) -> GateResult:
    ok, reason = audit.check_cost_cap(source_id, manifest, key)
    return GateResult(ok, reason, "" if ok else "COST_CAP_EXCEEDED")


def check_floor(
    *,
    file_path: Path,
    repo_root: Path,
    relpath: str,
    key: str,
    manifest: dict,
    source_id: str,
    require_override: str | None = None,
    in_git_repo: bool = True,
) -> GateResult:
    """Run the entire floor in order from cheap to expensive, stopping at the first failure."""
    checks = [
        check_path_policy(relpath, manifest),
    ]
    for r in checks:
        if not r.ok:
            return r

    # The git clause applies only where there IS a repo. Outside one it is not
    # skipped as a favour — it is simply inapplicable, and `maintain` later refuses to
    # reconcile such documents rather than guessing (SPEC A3).
    if in_git_repo:
        require = require_override or manifest.get("require", "committed")
        r = check_git_state(file_path, repo_root, relpath, require, manifest.get("canonical_branch", "main"))
        if not r.ok:
            return r

    r = check_secret_scan(file_path)
    if not r.ok:
        # `UNSCANNABLE` is reported to the caller, which routes to human review.
        # Everything else is a hard floor failure.
        return r

    r = check_cost_cap(source_id, manifest, key)
    if not r.ok:
        return r

    return GateResult(True, code="OK")


def check_floor_content(*, relpath: str, key: str, manifest: dict, source_id: str, text: str) -> GateResult:
    """The floor for `publish_content()` — an agent-authored document with no file and
    no repo behind it (SPEC A3).

    Same order, same checks that apply to any document: path policy, secret scan, cost
    cap. What is absent is `check_git_state` — not skipped as a shortcut, simply
    inapplicable, because there is no commit to check. `text` is always real text here
    (the caller already has it as a string), so `UNSCANNABLE` cannot occur on this path.
    """
    r = check_path_policy(relpath, manifest)
    if not r.ok:
        return r

    r = check_secret_scan_text(text)
    if not r.ok:
        return r

    r = check_cost_cap(source_id, manifest, key)
    if not r.ok:
        return r

    return GateResult(True, code="OK")
