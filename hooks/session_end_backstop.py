#!/usr/bin/env python3
"""Hook Stop / SessionEnd — the PRIMARY MECHANISM of the awareness reminder
layer (SPEC S11).

Unlike PostToolUse (which only catches Write|Edit), this backstop scans the
ENTIRE set of committed files matching the manifest that the audit has never
recorded — catching files created via Bash/heredoc/git-apply, multiple files
in a single turn, and the case where no agent ran an assessment for the whole
session. Shared by both Stop and SessionEnd.

Notify-only in phase 1 — does NOT set "decision": "block" (which would
prevent Claude Code from stopping). Must check `stop_hook_active` to avoid a
loop (in case the hook itself re-triggers the Stop pipeline).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import output_additional_context, read_hook_input  # noqa: E402

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


def main() -> int:
    data = read_hook_input()
    if data.get("stop_hook_active"):
        return 0  # guard against a loop

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

    _log_unassessed(m["source_id"], unassessed)

    shown = unassessed[:10]
    more = f" (+{len(unassessed) - 10} more files)" if len(unassessed) > 10 else ""
    hook_event_name = data.get("hook_event_name", "Stop")
    output_additional_context(
        f"[sag-maintain backstop] {len(unassessed)} committed file(s) match the "
        f"manifest but have never gone through a publish assessment: "
        f"{', '.join(shown)}{more}. If this is durable knowledge, run the "
        f"sag-publish skill on them before finishing.",
        hook_event_name,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
