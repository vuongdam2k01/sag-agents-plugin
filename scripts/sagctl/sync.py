"""Batch sync (SPEC S9/P5) — CLI-only, never an MCP tool (S8). Reuses
`publish_one()` for each file, with no separate replace/dedupe logic, so
batch crash-recovery and single-file publish crash-recovery behave identically
(REVIEW-OPUS #10).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import gitutil, globmatch, manifest as manifest_mod, publish as publish_mod


@dataclass
class SyncPlanItem:
    relpath: str
    action: str  # "publish" | "skip_no_assessment"


@dataclass
class SyncResult:
    published: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    renamed_detected: list[tuple[str, str]] = field(default_factory=list)


def _list_candidate_files(repo_root: Path, manifest: dict) -> list[Path]:
    # The fallback MUST match manifest.DEFAULTS["include"], gate.py's, and
    # routing.py's — three independent literals here previously (this one was
    # **/*.md, the other two were **/* already) is exactly how a manifest with
    # an explicit empty `include: []` would get sync and the publish floor
    # disagreeing about what "everything" means (SPEC A3).
    include = manifest.get("include") or manifest_mod.DEFAULTS["include"]
    exclude = manifest.get("exclude") or []
    seen: set[Path] = set()
    for pattern in include:
        for p in repo_root.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(repo_root).as_posix()
            if globmatch.match_any(rel, exclude):
                continue
            seen.add(p)
    return sorted(seen)


def detect_renames(candidate_files: list[Path], repo_root: Path) -> dict[str, str]:
    """Detect renames via matching blob sha — a newly appeared file with a blob
    identical to a document already published under a different path (SPEC S9,
    REVIEW-OPUS #10)."""
    by_blob: dict[str, str] = {}
    for p in candidate_files:
        try:
            blob = gitutil.hash_object(p)
        except Exception:
            continue
        rel = p.relative_to(repo_root).as_posix()
        by_blob[blob] = rel
    return by_blob


def plan(manifest_path: Path, *, require_assessment: bool = True) -> list[SyncPlanItem]:
    m = manifest_mod.load(manifest_path)
    repo_root = manifest_mod.repo_root(m)
    files = _list_candidate_files(repo_root, m)
    if len(files) > m["max_files"]:
        raise RuntimeError(
            f"sync candidate {len(files)} files exceeds max_files={m['max_files']} — "
            f"narrow include/exclude or explicitly raise max_files in the manifest."
        )
    items = []
    for f in files:
        rel = f.relative_to(repo_root).as_posix()
        items.append(SyncPlanItem(relpath=rel, action="publish"))
    return items


def run(
    manifest_path: Path,
    *,
    dry_run: bool = True,
    agent: str = "sync",
    concurrency: int = 1,
    wait: bool = False,
) -> SyncResult:
    """Batch sync — defaults to dry_run=True, the caller must explicitly pass
    dry_run=False. concurrency stays sequential (=1) by default because SAG's
    write path is write-light/read-heavy (P1, AGENT-BEHAVIOR.md) — only raise
    parallelism after measuring throughput via selftest S14.
    """
    items = plan(manifest_path)
    result = SyncResult()
    m = manifest_mod.load(manifest_path)
    repo_root = manifest_mod.repo_root(m)

    for item in items:
        file_path = repo_root / item.relpath
        if dry_run:
            result.published.append(f"[dry-run] {item.relpath}")
            continue
        try:
            outcome = publish_mod.publish_one(
                file_path,
                assessment=None,  # sync runs on already-canonical content -- see sag-sync-project skill: only runs after review via queue/manual
                manual_token=None,
                agent=agent,
                trigger="maintenance",
                wait=wait,
            )
            if outcome.status == "queued":
                result.skipped.append(f"{item.relpath} (queued: {outcome.reason})")
            elif outcome.status == "skipped":
                result.skipped.append(f"{item.relpath} ({outcome.reason})")
            else:
                result.published.append(item.relpath)
        except publish_mod.PublishError as e:
            result.errors.append((item.relpath, str(e)))
    return result
