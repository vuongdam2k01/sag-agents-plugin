"""doctor.unassessed_files — the repo-wide scan the Stop/SessionEnd backstop
uses to find files nobody ever ran through publish_one().

Bug found live, 2026-08-02: `git status --porcelain -- <path>` prints nothing
both for a clean COMMITTED file and for an IGNORED file — the old code
treated "empty porcelain output" as proof of "committed", so a gitignored
file (e.g. under a `private/.gitignore` containing `*`) was reported as an
unassessed, publishable document. The backstop then nagged every single Stop
to publish a file the publish floor (`gate.check_git_state`) would always
reject with NOT_COMMITTED — an unwinnable loop for any gitignored directory.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _bootstrap  # noqa: F401

from sagctl import doctor


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


class TestUnassessedFilesIgnoresGitignoredFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        _init_repo(self.root)

        self._home_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._home_tmp.cleanup)
        self._env_patch = mock.patch.dict("os.environ", {"SAGCTL_HOME": self._home_tmp.name})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def _write_manifest(self, **overrides) -> Path:
        doc = {"source_id": "src-doctor", "include": ["**/*.md"], **overrides}
        p = self.root / ".sag-sync.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_gitignored_file_is_not_reported_as_unassessed(self):
        manifest_path = self._write_manifest()
        secret = self.root / "secret"
        secret.mkdir()
        (secret / ".gitignore").write_text("*\n", encoding="utf-8")
        (secret / "ignored.md").write_text("never tracked", encoding="utf-8")
        _git(["add", "."], self.root)
        _git(["commit", "-q", "-m", "init with gitignore"], self.root)

        result = doctor.unassessed_files(manifest_path)
        self.assertNotIn("secret/ignored.md", result)

    def test_a_genuinely_committed_unassessed_file_still_is_reported(self):
        """The fix must not overcorrect into silence — a real committed,
        never-assessed file is still exactly what this function exists to
        find."""
        manifest_path = self._write_manifest()
        (self.root / "tracked.md").write_text("real content", encoding="utf-8")
        _git(["add", "."], self.root)
        _git(["commit", "-q", "-m", "tracked doc"], self.root)

        result = doctor.unassessed_files(manifest_path)
        self.assertEqual(result, ["tracked.md"])

    def test_dirty_untracked_file_still_excluded_as_not_yet_committed(self):
        """Unchanged behaviour: a plain untracked (non-ignored) file has a
        non-empty porcelain status and is correctly excluded before the git
        clause added by this fix is even reached."""
        manifest_path = self._write_manifest()
        (self.root / "untracked.md").write_text("draft", encoding="utf-8")

        result = doctor.unassessed_files(manifest_path)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
