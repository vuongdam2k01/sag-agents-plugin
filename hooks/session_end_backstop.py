#!/usr/bin/env python3
"""Hook Stop / SessionEnd — the PRIMARY MECHANISM of the awareness reminder
layer (SPEC S11).

Unlike PostToolUse (which only catches Write|Edit), this backstop scans the
ENTIRE set of committed files matching the manifest that the audit has never
recorded — catching files created via Bash/heredoc/git-apply, multiple files
in a single turn, and the case where no agent ran an assessment for the whole
session. Shared by both Stop and SessionEnd.

Two failure modes found live (2026-08-02), both from the same root cause:
`doctor.unassessed_files()` is REPO-GLOBAL — it globs every committed file
under the manifest, with no notion of which session (or which concurrent
agent) produced them. Since `Stop` fires after every single assistant turn
in EVERY session working in that repo (it is not "end of session" despite
the name), an unrelated session doing unrelated work got interrupted every
turn with a reminder about files another session was actively evaluating for
publish — hijacking its actual task.

Fix: scope the reminder to files that changed since THIS session started
(`_common.read_session_start_commit`, recorded by the UserPromptSubmit hook —
infra that already existed for exactly this purpose but was never consulted
here), and only ever mention a given file once per session so a long session
doesn't get the same nudge on every subsequent Stop.

Notify-only — does NOT set "decision": "block" (which would prevent Claude
Code from stopping). Must check `stop_hook_active` to avoid a loop (in case
the hook itself re-triggers the Stop pipeline).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import output_additional_context, read_hook_input, read_session_start_commit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sagctl import config, doctor, gitutil, manifest as manifest_mod  # noqa: E402


def _log_unassessed(source_id: str, files: list[str]) -> None:
    """Log this for CROSS-SESSION visibility — at SessionEnd there may no
    longer be a way to show context to the user, so we need a durable place
    for `sagctl doctor` or a later session to read back."""
    path = config.source_dir(source_id) / "unassessed-log.jsonl"
    record = {"ts": datetime.now(timezone.utc).isoformat(), "files": files}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _own_share(unassessed: list[str], session_id: str, repo_root: Path) -> list[str]:
    """Which of the repo-wide unassessed files this SESSION is plausibly
    responsible for — those changed since this session's start commit. No
    marker (e.g. UserPromptSubmit never fired first) means we cannot attribute
    anything to this session, so stay silent rather than fall back to the old
    repo-global blast."""
    start = read_session_start_commit(session_id)
    if not start:
        return []
    changed = set(gitutil.files_changed_since(start, repo_root))
    return [f for f in unassessed if f in changed]


def _notified_cache_path(session_id: str) -> Path:
    return config.session_dir() / f"{session_id}-backstop-notified.json"


def _already_notified(session_id: str) -> set[str]:
    p = _notified_cache_path(session_id)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return set()


def _mark_notified(session_id: str, files: list[str]) -> None:
    p = _notified_cache_path(session_id)
    seen = _already_notified(session_id)
    seen.update(files)
    p.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def main() -> int:
    data = read_hook_input()
    if data.get("stop_hook_active"):
        return 0  # guard against a loop

    session_id = data.get("session_id", "unknown-session")
    cwd = Path(data.get("cwd", "."))
    repo_root = gitutil.toplevel(cwd)
    if repo_root is None:
        return 0

    try:
        manifest_path = manifest_mod.find_manifest(repo_root)
    except Exception:
        manifest_path = None
    if manifest_path is None:
        return 0

    try:
        m = manifest_mod.load(manifest_path)
    except manifest_mod.ManifestError:
        return 0

    unassessed = doctor.unassessed_files(manifest_path)
    if not unassessed:
        return 0

    # Full repo-wide backlog is still logged for `sagctl doctor` / a later
    # session to read back — that visibility is legitimate. What must NOT
    # happen is pushing the full backlog into an unrelated session's context.
    _log_unassessed(m["source_id"], unassessed)

    mine = _own_share(unassessed, session_id, repo_root)
    if not mine:
        return 0

    already = _already_notified(session_id)
    fresh = [f for f in mine if f not in already]
    if not fresh:
        return 0
    _mark_notified(session_id, fresh)

    shown = fresh[:10]
    more = f" (+{len(fresh) - 10} more files)" if len(fresh) > 10 else ""
    hook_event_name = data.get("hook_event_name", "Stop")
    output_additional_context(
        f"[sag-maintain backstop] {len(fresh)} file(s) changed in this session "
        f"match the manifest but have never gone through a publish assessment: "
        f"{', '.join(shown)}{more}. If this is durable knowledge, run the "
        f"sag-publish skill on them before finishing.",
        hook_event_name,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
