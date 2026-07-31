import os
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SAGCTL_HOME"] = self._tmp.name
        global config
        from sagctl import config as config_mod

        config = config_mod

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("SAGCTL_HOME", None)

    def test_source_dir_is_stable_hash(self):
        d1 = config.source_dir("my-source")
        d2 = config.source_dir("my-source")
        self.assertEqual(d1, d2)

    def test_source_dir_differs_by_source_id(self):
        d1 = config.source_dir("source-a")
        d2 = config.source_dir("source-b")
        self.assertNotEqual(d1, d2)

    def test_credentials_roundtrip(self):
        creds = config.Credentials("default")
        creds.set(url="http://localhost:8000", write_token="tok-abc")
        loaded = creds.require()
        self.assertEqual(loaded["url"], "http://localhost:8000")
        self.assertEqual(loaded["write_token"], "tok-abc")

    def test_credentials_missing_raises(self):
        creds = config.Credentials("nonexistent-profile")
        with self.assertRaises(RuntimeError):
            creds.require()

    def test_assert_no_repo_state_leak_detects_audit_file(self):
        with tempfile.TemporaryDirectory() as repo:
            repo_path = Path(repo)
            (repo_path / "audit.jsonl").write_text("{}", encoding="utf-8")
            with self.assertRaises(config.RepoStateLeakError):
                config.assert_no_repo_state_leak(repo_path)

    def test_assert_no_repo_state_leak_passes_when_clean(self):
        with tempfile.TemporaryDirectory() as repo:
            repo_path = Path(repo)
            (repo_path / ".sag-sync.json").write_text("{}", encoding="utf-8")
            config.assert_no_repo_state_leak(repo_path)  # does not raise


if __name__ == "__main__":
    unittest.main()
