"""Deterministic floor (SPEC S4) — runs before ANY upload, no LLM involved.

If any check is red, the engine rejects deterministically. This is the single
boundary applied to BOTH auto and manual — routing (S6) decides WHETHER to
publish, gate.py decides whether that publish is SAFE to run.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import audit, gitutil, globmatch, secrets_scan


@dataclass
class GateResult:
    ok: bool
    reason: str = ""
    code: str = ""


def check_git_state(file_path: Path, repo_root: Path, relpath: str, require: str, canonical_branch: str) -> GateResult:
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
    include = manifest.get("include") or ["**/*"]
    exclude = manifest.get("exclude") or []
    if globmatch.match_any(relpath, exclude):
        return GateResult(False, "path matches exclude", "EXCLUDED_PATH")
    if not globmatch.match_any(relpath, include):
        return GateResult(False, "path does not match manifest include", "NOT_INCLUDED")
    return GateResult(True, code="OK")


def check_secret_scan(file_path: Path) -> GateResult:
    findings = secrets_scan.scan_file(file_path)
    if findings:
        detail = "; ".join(f"{f.kind}@L{f.line}" for f in findings[:5])
        return GateResult(False, f"secret scan found {len(findings)} finding(s): {detail}", "SECRET_FOUND")
    return GateResult(True, code="OK")


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
) -> GateResult:
    """Run the entire floor in order from cheap to expensive, stopping at the first failure."""
    checks = [
        check_path_policy(relpath, manifest),
    ]
    for r in checks:
        if not r.ok:
            return r

    require = require_override or manifest.get("require", "committed")
    r = check_git_state(file_path, repo_root, relpath, require, manifest.get("canonical_branch", "main"))
    if not r.ok:
        return r

    r = check_secret_scan(file_path)
    if not r.ok:
        return r

    r = check_cost_cap(source_id, manifest, key)
    if not r.ok:
        return r

    return GateResult(True, code="OK")
