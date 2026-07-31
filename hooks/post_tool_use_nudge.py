#!/usr/bin/env python3
"""Hook PostToolUse (matcher: Write|Edit) — the secondary reminder layer, not
the primary mechanism (SPEC S11: the primary mechanism is the Stop/SessionEnd
backstop, because this hook misses files created via Bash/heredoc and cannot
catch multiple files in a single turn).

Nudges AT MOST ONCE per file per session to avoid alert fatigue when a
document is edited multiple times via Edit (REVIEW-OPUS §2d).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import output_additional_context, read_hook_input  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sagctl import config, manifest as manifest_mod  # noqa: E402

_MD_SUFFIXES = {".md", ".markdown"}


def _nudged_cache_path(session_id: str) -> Path:
    return config.session_dir() / f"{session_id}-nudged.json"


def _already_nudged(session_id: str, relpath: str) -> bool:
    p = _nudged_cache_path(session_id)
    if not p.exists():
        return False
    try:
        seen = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return relpath in seen


def _mark_nudged(session_id: str, relpath: str) -> None:
    p = _nudged_cache_path(session_id)
    seen = []
    if p.exists():
        try:
            seen = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            seen = []
    if relpath not in seen:
        seen.append(relpath)
    p.write_text(json.dumps(seen), encoding="utf-8")


def main() -> int:
    data = read_hook_input()
    session_id = data.get("session_id", "unknown-session")
    tool_input = data.get("tool_input", {}) or {}
    file_path_str = tool_input.get("file_path") or tool_input.get("path")
    if not file_path_str:
        return 0
    file_path = Path(file_path_str)
    if file_path.suffix.lower() not in _MD_SUFFIXES:
        return 0
    if not file_path.exists():
        return 0

    try:
        m = manifest_mod.load_for(file_path)
    except manifest_mod.ManifestError:
        return 0  # no ancestor manifest -> outside SAG's scope, stay silent

    try:
        relpath = manifest_mod.relpath_of(file_path, m)
    except manifest_mod.ManifestError:
        return 0

    if _already_nudged(session_id, relpath):
        return 0
    _mark_nudged(session_id, relpath)

    output_additional_context(
        f"[sag-publish nudge] Just wrote '{relpath}' — if this is durable knowledge "
        f"(ADR, requirement, design, runbook, research...), run the publish "
        f"assessment (skill sag-publish) after committing. This file will only be "
        f"nudged once per session.",
        "PostToolUse",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
