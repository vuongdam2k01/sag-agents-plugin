"""Shared utilities for the hook scripts (not a module of the sagctl package
— runs standalone, adding scripts/ to sys.path itself in order to import sagctl)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Force UTF-8 for stdout/stderr AS SOON AS this module is imported (every
# hook imports _common first) — the default Windows console (cp1252/cp437)
# crashes when printing Vietnamese text, and a hook's additionalContext
# always contains Vietnamese text.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def read_hook_input() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def output_additional_context(text: str, hook_event_name: str) -> None:
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": hook_event_name, "additionalContext": text}}
        )
    )


def session_marker_path(session_id: str) -> Path:
    from sagctl import config

    d = config.session_dir()
    return d / f"{session_id}-start-commit.txt"


def record_session_start_commit(session_id: str, repo_root: Path) -> None:
    from sagctl import gitutil

    marker = session_marker_path(session_id)
    if marker.exists():
        return
    try:
        commit = gitutil.head_commit(repo_root)
    except Exception:
        return
    marker.write_text(commit, encoding="utf-8")


def read_session_start_commit(session_id: str) -> str | None:
    marker = session_marker_path(session_id)
    if not marker.exists():
        return None
    return marker.read_text(encoding="utf-8").strip() or None
