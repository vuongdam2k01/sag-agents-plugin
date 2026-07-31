"""`sagctl doctor` — diagnostics, used as a backstop for agent tools that lack
enforceable hooks (Hermes, Codex — SPEC S11: "machine enforcement only exists
on Claude Code", elsewhere it's advisory + doctor).
"""
from __future__ import annotations

from pathlib import Path

from . import audit, gitutil, globmatch, manifest as manifest_mod, manual


def unassessed_files(manifest_path: Path, *, since_ref: str | None = None) -> list[str]:
    """A file matching the manifest's include, already committed, but WITHOUT a
    'published', 'queued', or 'publish_skipped' event in the audit log — meaning
    it was never run through publish_one() despite being eligible, a sign the
    hook was missed (SPEC S11).
    """
    m = manifest_mod.load(manifest_path)
    repo_root = manifest_mod.repo_root(m)
    source_id = m["source_id"]

    audited_relpaths = set()
    for rec in audit.read_all(source_id):
        key = rec.get("key") or (rec.get("assessment") or {}).get("path")
        if key:
            from . import keys as keys_mod

            audited_relpaths.add(keys_mod.decode_key(key, m["key_format"]))

    include = m.get("include") or ["**/*.md"]
    exclude = m.get("exclude") or []
    unassessed = []
    for pattern in include:
        for p in repo_root.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(repo_root).as_posix()
            if globmatch.match_any(rel, exclude):
                continue
            status = gitutil.status_porcelain_for(rel, repo_root)
            if status.strip():
                continue  # not committed -- not yet eligible, doesn't count as "missed"
            if rel not in audited_relpaths:
                unassessed.append(rel)
    return sorted(unassessed)


def health_report(source_id: str) -> dict:
    tokens_cleaned = manual.cleanup_expired()
    fail_rates = audit.fail_rate_by_agent_route(source_id)
    recent = audit.read_since(source_id, days=1)
    events_today = {}
    for rec in recent:
        ev = rec.get("event", "unknown")
        events_today[ev] = events_today.get(ev, 0) + 1
    return {
        "source_id": source_id,
        "expired_manual_tokens_cleaned": tokens_cleaned,
        "fail_rate_by_agent_route": fail_rates,
        "events_last_24h": events_today,
    }
