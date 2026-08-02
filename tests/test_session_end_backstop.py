"""hooks/session_end_backstop.py — the Stop/SessionEnd awareness backstop.

Bug found live, 2026-08-02: `doctor.unassessed_files()` is repo-global (every
committed file matching the manifest, from any point in the repo's history).
`Stop` fires after every single assistant turn, in every session working in
that repo — so an unrelated session doing unrelated work got the same
"go publish this" reminder shoved into its context on every turn, for files
another session was actively evaluating. That is the bug this test guards:
the reminder must be scoped to what changed since THIS session started, and
must not repeat once shown.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import _bootstrap  # noqa: F401

_HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

import session_end_backstop as backstop  # noqa: E402
from _common import record_session_start_commit  # noqa: E402


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


def _run_hook(payload: dict) -> dict | None:
    """Run main() with `payload` as stdin, capture the JSON line it prints (if
    any). Returns None if the hook stayed silent."""
    buf = StringIO()
    with mock.patch("sys.stdin", StringIO(json.dumps(payload))), mock.patch("sys.stdout", buf):
        backstop.main()
    out = buf.getvalue().strip()
    return json.loads(out) if out else None


class TestSessionScoping(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        _init_repo(self.root)
        (self.root / ".sag-sync.json").write_text(json.dumps({"source_id": "src-x"}), encoding="utf-8")
        _git(["add", "."], self.root)
        _git(["commit", "-q", "-m", "init"], self.root)

        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self._env_patch = mock.patch.dict(os.environ, {"SAGCTL_HOME": self._home_tmp.name})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_unrelated_session_is_not_nudged_about_a_pre_existing_backlog(self):
        """The reported bug: session B (unrelated work) must not be told to
        publish a file that already existed before B's session even started —
        that backlog belongs to whichever session actually produced it."""
        (self.root / "docs.md").write_text("pre-existing content", encoding="utf-8")
        _git(["add", "."], self.root)
        _git(["commit", "-q", "-m", "pre-existing unassessed doc"], self.root)

        record_session_start_commit("session-b", self.root)

        out = _run_hook({"session_id": "session-b", "cwd": str(self.root), "hook_event_name": "Stop"})
        self.assertIsNone(out, f"unrelated session was nudged about someone else's backlog: {out}")

    def test_own_session_new_file_still_nudges(self):
        """A file committed AFTER this session's own start marker is fair game
        — that is this session's own unassessed work, the backstop's real job."""
        record_session_start_commit("session-a", self.root)

        (self.root / "new.md").write_text("new content", encoding="utf-8")
        _git(["add", "."], self.root)
        _git(["commit", "-q", "-m", "session-a's own doc"], self.root)

        out = _run_hook({"session_id": "session-a", "cwd": str(self.root), "hook_event_name": "Stop"})
        self.assertIsNotNone(out)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("new.md", ctx)

    def test_same_file_is_not_renudged_every_turn(self):
        """Stop fires on every turn, not just once — a file already surfaced
        this session must not be repeated, or a long session gets the same
        reminder spammed into its context turn after turn."""
        record_session_start_commit("session-a", self.root)
        (self.root / "new.md").write_text("new content", encoding="utf-8")
        _git(["add", "."], self.root)
        _git(["commit", "-q", "-m", "session-a's own doc"], self.root)

        first = _run_hook({"session_id": "session-a", "cwd": str(self.root), "hook_event_name": "Stop"})
        self.assertIsNotNone(first)

        second = _run_hook({"session_id": "session-a", "cwd": str(self.root), "hook_event_name": "Stop"})
        self.assertIsNone(second, f"same file re-nudged on the next turn: {second}")

    def test_no_start_marker_stays_silent_rather_than_blasting_the_whole_repo(self):
        """If UserPromptSubmit never fired first (no marker recorded), we cannot
        attribute anything to this session — the old behaviour of falling back
        to the full repo-wide backlog is exactly the bug being fixed here."""
        (self.root / "docs.md").write_text("content", encoding="utf-8")
        _git(["add", "."], self.root)
        _git(["commit", "-q", "-m", "doc"], self.root)

        out = _run_hook({"session_id": "session-no-marker", "cwd": str(self.root), "hook_event_name": "Stop"})
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
