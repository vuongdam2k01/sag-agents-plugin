import os
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401


class TestManualToken(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SAGCTL_HOME"] = self._tmp.name
        # import after setting the env var so the config module uses the correct temp home
        global manual, config
        from sagctl import config as config_mod
        from sagctl import manual as manual_mod

        config = config_mod
        manual = manual_mod

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("SAGCTL_HOME", None)

    def test_mint_then_consume_succeeds(self):
        manual.mint("docs/x.md", "tok1")
        self.assertTrue(manual.consume("tok1", "docs/x.md"))

    def test_consume_is_single_use(self):
        manual.mint("docs/x.md", "tok1")
        self.assertTrue(manual.consume("tok1", "docs/x.md"))
        self.assertFalse(manual.consume("tok1", "docs/x.md"))

    def test_consume_wrong_args_fails(self):
        manual.mint("docs/x.md", "tok1")
        self.assertFalse(manual.consume("tok1", "docs/OTHER.md"))

    def test_consume_unknown_token_fails(self):
        self.assertFalse(manual.consume("never-minted", "docs/x.md"))

    def test_expired_token_fails(self):
        import time

        manual.mint("docs/x.md", "tok1")
        path = config.session_dir() / "token-tok1.json"
        import json

        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["expires_at"] = time.time() - 1
        path.write_text(json.dumps(rec), encoding="utf-8")
        self.assertFalse(manual.consume("tok1", "docs/x.md"))

    def test_cleanup_expired_removes_stale_tokens(self):
        import time
        import json

        manual.mint("docs/x.md", "tok1")
        path = config.session_dir() / "token-tok1.json"
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["expires_at"] = time.time() - 1
        path.write_text(json.dumps(rec), encoding="utf-8")
        removed = manual.cleanup_expired()
        self.assertEqual(removed, 1)
        self.assertFalse(path.exists())

    def test_cleanup_expired_ignores_other_hooks_json_caches(self):
        """Crashed live, 2026-08-02, via `sagctl doctor`: session_dir() is shared
        scratch space for the post_tool_use_nudge/session_end_backstop hooks too,
        which write their own `*.json` caches there holding a *list*, not a token
        record — cleanup_expired()'s glob used to pick those up and crash on
        `.get()`. It must now leave them alone (and still do its real job)."""
        import json

        (config.session_dir() / "sess123-nudged.json").write_text(
            json.dumps(["docs/a.md"]), encoding="utf-8"
        )
        (config.session_dir() / "sess123-backstop-notified.json").write_text(
            json.dumps(["docs/b.md"]), encoding="utf-8"
        )
        manual.mint("docs/x.md", "tok1")

        removed = manual.cleanup_expired()

        self.assertEqual(removed, 0)  # the one real token isn't expired yet
        self.assertTrue((config.session_dir() / "sess123-nudged.json").exists())
        self.assertTrue((config.session_dir() / "sess123-backstop-notified.json").exists())


if __name__ == "__main__":
    unittest.main()
