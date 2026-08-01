"""Periodic maintenance (SPEC S10) — defaults to PROPOSING, does not auto-delete.
The one exception: a key duplicate with DEFINITIVE ancestry is auto-removed for
the losing copy (ancestry has enough data to reach a certain conclusion, no
human judgment needed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import audit, gitutil, manifest as manifest_mod, provenance, state
from .restclient import SagClient


@dataclass
class DedupeOutcome:
    key: str
    action: str  # "auto_removed_loser" | "unknown_needs_human" | "no_duplicate"
    kept_document_id: str | None = None
    removed_document_id: str | None = None
    reason: str = ""


def tie_break(
    docs_same_key: list[dict],
    repo_root: Path,
    canonical_branch: str,
) -> tuple[dict | None, dict | None, str]:
    """Return (winner, loser, reason). If UNKNOWN, return (None, None, reason) —
    nothing gets deleted. Algorithm (REVIEW-OPUS C3, finalized in SPEC S10):

      1. cat-file -e before is-ancestor (distinguishes 'losing' from 'commit unknown')
      2. is-ancestor(A, B) true -> B wins
      3. both are ancestors (parallel branch already merged) -> smaller rev-list --count wins
      4. cannot be determined -> UNKNOWN, no deletion, report to a human
    """
    if len(docs_same_key) != 2:
        return None, None, f"tie_break only handles exactly 2 copies, got {len(docs_same_key)}"

    a, b = docs_same_key
    commit_a = provenance.extract_frontmatter_field(a.get("_content", "") or "", "sag_source_commit") or a.get("sag_source_commit")
    commit_b = provenance.extract_frontmatter_field(b.get("_content", "") or "", "sag_source_commit") or b.get("sag_source_commit")

    if not commit_a or not commit_b:
        return None, None, "sag_source_commit is missing from the provenance of one or both copies"

    fetched = gitutil.fetch(repo_root, "origin", canonical_branch)
    if not fetched:
        return None, None, "git fetch failed — no dedupe, reporting only"

    ref = f"origin/{canonical_branch}"
    exists_a = gitutil.commit_exists(commit_a, repo_root)
    exists_b = gitutil.commit_exists(commit_b, repo_root)
    if not exists_a or not exists_b:
        return None, None, f"commit not present in the clone (a_exists={exists_a}, b_exists={exists_b}) -> UNKNOWN"

    anc_a = gitutil.is_ancestor(commit_a, ref, repo_root)
    anc_b = gitutil.is_ancestor(commit_b, ref, repo_root)

    if anc_a and not anc_b:
        return a, b, f"{commit_b[:7]} is not an ancestor of {ref}, {commit_a[:7]} is an ancestor -> a wins"
    if anc_b and not anc_a:
        return b, a, f"{commit_a[:7]} is not an ancestor of {ref}, {commit_b[:7]} is an ancestor -> b wins"
    if anc_a and anc_b:
        count_a = gitutil.rev_list_count(commit_a, ref, repo_root)
        count_b = gitutil.rev_list_count(commit_b, ref, repo_root)
        if count_a < 0 or count_b < 0:
            return None, None, "rev-list --count failed -> UNKNOWN"
        if count_a == count_b:
            return None, None, "both distances are equal -> UNKNOWN"
        winner, loser = (a, b) if count_a < count_b else (b, a)
        return winner, loser, f"both are ancestors of {ref}; the copy closer to HEAD wins (rev-list count {min(count_a,count_b)})"
    return None, None, "neither side is an ancestor of canonical_branch -> UNKNOWN"


def dedupe_source(client: SagClient, source_id: str, repo_root: Path, canonical_branch: str) -> list[DedupeOutcome]:
    docs, truncated = client.list_documents_all(source_id)
    if truncated:
        return [DedupeOutcome(key="*", action="unknown_needs_human", reason="list_documents shows signs of pagination/truncation, stopping dedupe")]

    by_key: dict[str, list[dict]] = {}
    for d in docs:
        by_key.setdefault(d.get("filename", ""), []).append(d)

    outcomes: list[DedupeOutcome] = []
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        # need content to read sag_source_commit -> fetch document content if the client supports it
        for d in group:
            # DocumentOut (get_document) does NOT have a content/text field — confirmed
            # via selftest S13/S7 on sag.home. The parsed content (including
            # provenance frontmatter) lives on the separate /parsed endpoint.
            d["_content"] = client.get_document_parsed(source_id, d["id"])
        if len(group) > 2:
            outcomes.append(DedupeOutcome(key=key, action="unknown_needs_human", reason=f"{len(group)} copies share this key, needs human handling"))
            continue
        winner, loser, reason = tie_break(group, repo_root, canonical_branch)
        if winner is None:
            outcomes.append(DedupeOutcome(key=key, action="unknown_needs_human", reason=reason))
            continue
        client.delete_document(source_id, loser["id"], tolerate_404=True)
        audit.append(
            source_id,
            {"event": "dedupe_auto_removed", "key": key, "kept": winner["id"], "removed": loser["id"], "reason": reason},
        )
        outcomes.append(
            DedupeOutcome(key=key, action="auto_removed_loser", kept_document_id=winner["id"], removed_document_id=loser["id"], reason=reason)
        )
    return outcomes


def _reconcilable(source_id: str, key: str) -> bool:
    """Was this document ever a path inside THIS repo? Orphan/stale-branch detection
    both ask "does the path still exist at HEAD" — meaningless, and dangerous, for a
    document that was never in the repo to begin with (an authored synthesis, a file
    published from outside any Git checkout — SPEC A3). The state store's provenance
    record is authoritative here: `sag_in_git` says so directly. A document with no
    state-store record at all predates A1/A3 and is treated as reconcilable, matching
    the engine's behavior before this distinction existed.
    """
    rec = state.provenance_get(source_id, key)
    if rec is None:
        return True
    return bool(rec.get("sag_in_git", True))


def find_orphans(client: SagClient, source_id: str, repo_root: Path, canonical_branch: str) -> list[dict]:
    """An 'orphan' = a document in SAG whose corresponding path no longer exists
    at the HEAD of canonical_branch (defined by Git HEAD, NOT by lock —
    REVIEW-OPUS F14/F28: a single-file publish does not write a lock, so 'outside
    the lock' is NOT an orphan).
    """
    gitutil.fetch(repo_root, "origin", canonical_branch)
    ref = f"origin/{canonical_branch}"
    docs, truncated = client.list_documents_all(source_id)
    orphans = []
    for d in docs:
        key = d.get("filename", "")
        if not key:
            continue
        if not _reconcilable(source_id, key):
            continue
        # key may be flat-encoded; assume the caller passes key_format via closure
        # if the path does not exist at ref -> orphan
        exists = gitutil.path_exists_at_ref(key, ref, repo_root)
        if not exists:
            orphans.append({**d, "_orphan_reason": f"path '{key}' does not exist at {ref}"})
    return orphans


def find_stale_branch(client: SagClient, source_id: str, repo_root: Path, manifest: dict) -> list[dict]:
    """A document published with require=committed on a working branch that has
    never reached canonical_branch after N days -> suspected forgotten, propose
    unpublish.

    Compares both ancestry AND blob-at-ref so a squash-merge that loses the
    original SHA doesn't trigger a false positive (REVIEW-OPUS gate turn2,
    objection D1).
    """
    import time

    gitutil.fetch(repo_root, "origin", manifest["canonical_branch"])
    ref = f"origin/{manifest['canonical_branch']}"
    threshold_seconds = manifest["stale_branch_days"] * 86400
    now = time.time()

    docs, _ = client.list_documents_all(source_id)
    stale = []
    for d in docs:
        content = client.get_document_parsed(source_id, d["id"])
        commit = provenance.extract_frontmatter_field(content, "sag_source_commit")
        blob = provenance.extract_frontmatter_field(content, "sag_source_blob")
        published_at = provenance.extract_frontmatter_field(content, "sag_published_at")
        key = provenance.extract_frontmatter_field(content, "sag_key") or d.get("filename", "")
        if not _reconcilable(source_id, key):
            continue
        if not commit or not published_at:
            continue
        try:
            from datetime import datetime

            age = now - datetime.fromisoformat(published_at).timestamp()
        except ValueError:
            continue
        if age < threshold_seconds:
            continue
        ancestor_ok = gitutil.commit_exists(commit, repo_root) and gitutil.is_ancestor(commit, ref, repo_root)
        blob_ok = False
        if blob and gitutil.path_exists_at_ref(key, ref, repo_root):
            blob_ok = gitutil.blob_at_ref(key, ref, repo_root) == blob
        if not ancestor_ok and not blob_ok:
            stale.append({**d, "_stale_reason": f"commit {commit[:7]} has not reached {ref} after {manifest['stale_branch_days']} days"})
    return stale


def review_self_gate(source_id: str, *, days: int = 7) -> dict:
    """Post-hoc review of documents published via route=auto in the last N days.
    Returns a report — the actual action (unpublish) is a decision for a
    human/reviewer, this function only lists candidates (SPEC S10: defaults to
    proposing).
    """
    records = audit.read_since(source_id, days)
    candidates = [r for r in records if r.get("event") == "published" and r.get("route") == "auto"]
    return {"source_id": source_id, "window_days": days, "candidates": candidates, "count": len(candidates)}
