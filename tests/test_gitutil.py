"""gitutil.files_changed_since — the primitive the Stop/SessionEnd backstop
uses to attribute repo-wide state back to a single session (found live,
2026-08-02: see test_session_end_backstop.py for the bug this closes)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from sagctl import gitutil


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


class TestFilesChangedSince(unittest.TestCase):
    def test_reports_files_touched_after_the_marker_commit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _init_repo(root)
            (root / "a.md").write_text("a", encoding="utf-8")
            _git(["add", "."], root)
            _git(["commit", "-q", "-m", "start"], root)
            start = gitutil.head_commit(root)

            (root / "b.md").write_text("b", encoding="utf-8")
            _git(["add", "."], root)
            _git(["commit", "-q", "-m", "second"], root)

            changed = gitutil.files_changed_since(start, root)
            self.assertEqual(changed, ["b.md"])

    def test_no_changes_since_marker_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _init_repo(root)
            (root / "a.md").write_text("a", encoding="utf-8")
            _git(["add", "."], root)
            _git(["commit", "-q", "-m", "start"], root)
            start = gitutil.head_commit(root)

            self.assertEqual(gitutil.files_changed_since(start, root), [])

    def test_unknown_sha_degrades_to_empty_not_an_exception(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _init_repo(root)
            (root / "a.md").write_text("a", encoding="utf-8")
            _git(["add", "."], root)
            _git(["commit", "-q", "-m", "start"], root)

            self.assertEqual(gitutil.files_changed_since("0" * 40, root), [])


if __name__ == "__main__":
    unittest.main()
