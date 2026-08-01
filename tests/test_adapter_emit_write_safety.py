"""`sagctl adapter-emit --write` must never destroy a real settings.json (regression).

What happened: a user ran `--write . --force` in a project whose `.claude/settings.json`
already held a large amount of unrelated, hand-tuned configuration. `--force` governed
BOTH "overwrite a file we generated before" (safe — .mcp.json is wholly ours) and
"overwrite a merge-target that predates us" (never safe) as the same flag. The command's
own code comment said clobbering unrelated settings "is not this command's job", and then
did exactly that. No backup was made; the file was gone.

The fix removes the second meaning entirely: a merge-target is never written by this
command, with or without --force. These tests exercise the real CLI entry point
(`sagctl.__main__.main`) against a real temp directory holding realistic pre-existing
content, not just the generator's in-memory output — the bug was in the write path, not
in what content was generated.
"""
import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from sagctl.__main__ import main


REALISTIC_EXISTING_SETTINGS = {
    "permissions": {
        "allow": ["Bash(npm run *)", "Bash(git *)", "mcp__some_other_plugin__*"],
        "ask": ["Bash(rm *)"],
        "deny": ["Bash(sudo *)"],
    },
    "hooks": {
        "PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "echo custom"}]}]
    },
    "env": {"SOME_UNRELATED_VAR": "kept"},
}


class TestWriteNeverClobbersAMergeTarget(unittest.TestCase):
    def _project_with_real_settings(self) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / ".sag-sync.json").write_text(json.dumps({"source_id": "s"}), encoding="utf-8")
        settings_dir = root / ".claude"
        settings_dir.mkdir()
        settings_path = settings_dir / "settings.json"
        settings_path.write_text(json.dumps(REALISTIC_EXISTING_SETTINGS, indent=2), encoding="utf-8")
        return root

    def test_force_does_not_touch_an_existing_settings_json(self):
        root = self._project_with_real_settings()
        settings_path = root / ".claude" / "settings.json"
        before = settings_path.read_text(encoding="utf-8")

        main(["adapter-emit", "claude-code", "--manifest", str(root / ".sag-sync.json"),
              "--write", str(root), "--force"])

        after = settings_path.read_text(encoding="utf-8")
        self.assertEqual(before, after, "settings.json must be byte-for-byte untouched")
        self.assertEqual(json.loads(after), REALISTIC_EXISTING_SETTINGS)

    def test_without_force_also_does_not_touch_it(self):
        root = self._project_with_real_settings()
        settings_path = root / ".claude" / "settings.json"
        before = settings_path.read_text(encoding="utf-8")

        main(["adapter-emit", "claude-code", "--manifest", str(root / ".sag-sync.json"),
              "--write", str(root)])

        self.assertEqual(before, settings_path.read_text(encoding="utf-8"))

    def test_mcp_json_still_gets_written_with_force(self):
        """The fix must not regress the legitimate case: .mcp.json is wholly ours and
        --force should still let it be regenerated."""
        root = self._project_with_real_settings()
        mcp_path = root / ".mcp.json"
        mcp_path.write_text('{"old": "content we generated before"}', encoding="utf-8")

        main(["adapter-emit", "claude-code", "--manifest", str(root / ".sag-sync.json"),
              "--write", str(root), "--force"])

        doc = json.loads(mcp_path.read_text(encoding="utf-8"))
        self.assertIn("source_id=s", doc["mcpServers"]["sag"]["url"])

    def test_mcp_json_without_force_is_left_alone_when_it_already_exists(self):
        root = self._project_with_real_settings()
        mcp_path = root / ".mcp.json"
        mcp_path.write_text('{"old": "content"}', encoding="utf-8")

        main(["adapter-emit", "claude-code", "--manifest", str(root / ".sag-sync.json"),
              "--write", str(root)])

        self.assertEqual(mcp_path.read_text(encoding="utf-8"), '{"old": "content"}')

    def test_settings_json_content_is_still_printed_for_manual_merging(self):
        import io
        from contextlib import redirect_stderr

        root = self._project_with_real_settings()
        buf = io.StringIO()
        with redirect_stderr(buf):
            main(["adapter-emit", "claude-code", "--manifest", str(root / ".sag-sync.json"),
                  "--write", str(root), "--force"])
        self.assertIn("mcp__sagw__sag_publish", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
