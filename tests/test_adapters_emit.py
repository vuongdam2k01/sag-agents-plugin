"""adapter-emit generation tests (SPEC amendment A2).

The property that matters: a `source_id` is declared once in the manifest and every
agent-side config is derived from it. These tests assert the derivation, and assert
that emitting WITHOUT a source_id produces a visibly unscoped config rather than a
silently unscoped one.
"""
import json
import unittest

import _bootstrap  # noqa: F401

from sagctl import adapters_emit


class TestScopedUrls(unittest.TestCase):
    def test_claude_code_mcp_json_carries_the_source_id(self):
        files = adapters_emit.emit_files("claude-code", source_id="project-a-knowledge")
        mcp = next(f for f in files if f.path == ".mcp.json")
        doc = json.loads(mcp.content)
        self.assertEqual(
            doc["mcpServers"]["sag"]["url"], "${SAG_URL}/mcp/?source_id=project-a-knowledge"
        )

    def test_claude_code_without_source_id_is_unscoped_and_says_so(self):
        files = adapters_emit.emit_files("claude-code", source_id=None)
        mcp = next(f for f in files if f.path == ".mcp.json")
        doc = json.loads(mcp.content)
        self.assertEqual(doc["mcpServers"]["sag"]["url"], "${SAG_URL}/mcp/")
        self.assertIn("UNSCOPED", mcp.note)

    def test_hermes_and_codex_carry_the_same_source_id(self):
        for target in ("hermes", "codex"):
            with self.subTest(target=target):
                text = adapters_emit.emit(target, source_id="project-a-knowledge")
                self.assertIn("/mcp/?source_id=project-a-knowledge", text)

    def test_every_target_wires_the_shared_state_service(self):
        for target in adapters_emit.TARGETS:
            with self.subTest(target=target):
                text = adapters_emit.emit(target, source_id="s")
                self.assertIn("SAGCTL_STATE_URL", text)
                self.assertIn("SAGCTL_STATE_TOKEN", text)

    def test_every_target_tags_its_agent_identity_distinctly(self):
        agents = {}
        for target in adapters_emit.TARGETS:
            text = adapters_emit.emit(target, source_id="s")
            agents[target] = text
        self.assertIn('"SAGCTL_AGENT": "claude-code"', agents["claude-code"])
        self.assertIn('SAGCTL_AGENT: "hermes:${HERMES_PROFILE_NAME}"', agents["hermes"])
        self.assertIn('SAGCTL_AGENT = "codex"', agents["codex"])

    def test_write_token_never_appears_in_any_generated_config(self):
        """S12: the write token lives in ~/.sagctl/credentials.json and must never be
        handed to an agent tool's config."""
        for target in adapters_emit.TARGETS:
            with self.subTest(target=target):
                text = adapters_emit.emit(target, source_id="s")
                self.assertNotIn("SAG_WRITE_TOKEN", text)
                self.assertNotIn("write_token", text)

    def test_plugin_root_is_substituted_for_hermes_and_codex(self):
        for target in ("hermes", "codex"):
            with self.subTest(target=target):
                text = adapters_emit.emit(target, source_id="s", plugin_root="/srv/sag-plugin/")
                self.assertIn("/srv/sag-plugin/scripts/sagw_server.py", text)
                self.assertNotIn("//scripts", text)

    def test_claude_code_uses_the_plugin_root_variable_not_a_path(self):
        """Claude Code resolves ${CLAUDE_PLUGIN_ROOT} itself; a baked path would break
        on every other machine."""
        files = adapters_emit.emit_files("claude-code", source_id="s")
        mcp = json.loads(next(f for f in files if f.path == ".mcp.json").content)
        self.assertEqual(
            mcp["mcpServers"]["sagw"]["args"], ["${CLAUDE_PLUGIN_ROOT}/scripts/sagw_server.py"]
        )

    def test_settings_block_comes_from_the_static_adapter_file(self):
        files = adapters_emit.emit_files("claude-code", source_id="s")
        settings = json.loads(next(f for f in files if f.path == ".claude/settings.json").content)
        perms = settings["permissions"]
        self.assertIn("mcp__sagw__sag_publish", perms["allow"])
        self.assertIn("mcp__sagw__sag_unpublish", perms["ask"])
        self.assertIn("Bash(sagctl sync*)", perms["deny"])

    def test_files_that_normally_exist_are_marked_merge(self):
        merge_targets = {
            ("claude-code", ".claude/settings.json"),
            ("hermes", "config.yaml"),
            ("codex", "config.toml"),
        }
        for target, path in merge_targets:
            with self.subTest(target=target, path=path):
                f = next(x for x in adapters_emit.emit_files(target, source_id="s") if x.path == path)
                self.assertTrue(f.merge)

    def test_mcp_json_is_not_a_merge_target(self):
        """.mcp.json is wholly ours — writing it directly is safe and is the point."""
        f = next(x for x in adapters_emit.emit_files("claude-code", source_id="s") if x.path == ".mcp.json")
        self.assertFalse(f.merge)

    def test_invalid_target_rejected(self):
        with self.assertRaises(ValueError):
            adapters_emit.emit_files("emacs", source_id="s")

    def test_generated_json_is_valid_for_every_json_artifact(self):
        for f in adapters_emit.emit_files("claude-code", source_id="s"):
            if f.path.endswith(".json"):
                json.loads(f.content)  # raises on malformed output


if __name__ == "__main__":
    unittest.main()
