"""Regression guard: no shipped or generated config may name an interpreter.

Confirmed broken in the field (Ubuntu 24.04, 2026-08-01): a stock Ubuntu has
`python3` and no `python`, so `"command": "python"` meant the `sagw` MCP server never
started and all four hooks died. Hooks failing is the nastier half — they fail
*silently*, so the agent keeps working and simply never reports an unassessed file.

There is no interpreter name that is correct everywhere: Ubuntu ships only `python3`,
the python.org installer on Windows ships only `python`. So configs route through the
`sagctl` shim, which has `sys.executable` baked in at install time.
"""
import json
import re
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from sagctl import adapters_emit

REPO = Path(__file__).resolve().parent.parent

# `python -c`, `python3 -m` etc. inside a DENY rule are fine — those are patterns being
# blocked, not commands being run. Only executable positions matter.
_BAD_COMMAND = re.compile(r'"command"\s*:\s*"python3?(\.exe)?"')


class TestShippedConfigs(unittest.TestCase):
    def test_plugin_root_does_not_ship_an_mcp_json(self):
        """The plugin used to ship its own root .mcp.json, auto-registered by Claude
        Code the moment the plugin is enabled — unscoped (no source_id) and a second,
        independently-versioned `sagw` alongside whatever a project's own adapter-emit
        output registers (found live, 2026-08-02). MCP config is now generated
        per-project, always scoped, via `sagctl adapter-emit claude-code --write .` —
        see TestGeneratedConfigs below."""
        self.assertFalse((REPO / ".mcp.json").exists())

    def test_hooks_json_does_not_name_an_interpreter(self):
        raw = (REPO / "hooks" / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("python", raw)
        doc = json.loads(raw)
        commands = [
            h["command"]
            for event in doc["hooks"].values()
            for group in event
            for h in group["hooks"]
        ]
        self.assertEqual(len(commands), 4)
        for cmd in commands:
            with self.subTest(cmd=cmd):
                self.assertTrue(cmd.startswith("sagctl hook "), cmd)

    def test_every_hook_command_names_a_real_hook(self):
        from sagctl.__main__ import HOOK_SCRIPTS

        doc = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        for event in doc["hooks"].values():
            for group in event:
                for h in group["hooks"]:
                    name = h["command"].split()[-1]
                    with self.subTest(name=name):
                        self.assertIn(name, HOOK_SCRIPTS)
                        self.assertTrue((REPO / "hooks" / HOOK_SCRIPTS[name]).is_file())


class TestGeneratedConfigs(unittest.TestCase):
    def test_no_target_emits_an_interpreter_as_the_command(self):
        for target in adapters_emit.TARGETS:
            with self.subTest(target=target):
                text = adapters_emit.emit(target, source_id="s")
                self.assertIsNone(_BAD_COMMAND.search(text), f"{target} names an interpreter")
                self.assertNotIn('command = "python"', text)
                self.assertNotIn('command: "python"', text)

    def test_every_target_invokes_sagw_through_the_shim(self):
        for target in adapters_emit.TARGETS:
            with self.subTest(target=target):
                text = adapters_emit.emit(target, source_id="s")
                self.assertIn("serve-mcp", text)

    def test_claude_code_mcp_json_is_shim_based(self):
        files = adapters_emit.emit_files("claude-code", source_id="s")
        doc = json.loads(next(f for f in files if f.path == ".mcp.json").content)
        self.assertEqual(doc["mcpServers"]["sagw"]["command"], "sagctl")


class TestVersionedInstallDetection(unittest.TestCase):
    """A shim baked against a version-pinned cache path silently keeps running the old
    engine after `claude plugin update`. Observed layout, from a real install."""

    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "install_shim", REPO / "scripts" / "install-shim.py"
        )
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_versioned_cache_path_warns(self):
        root = Path("/home/ubuntu/.claude/plugins/cache/sag-agents-marketplace/sag-agents/0.1.0")
        warning = self.mod._versioned_install_warning(root)
        self.assertIsNotNone(warning)
        self.assertIn("stale engine", warning)

    def test_warning_points_at_the_stable_marketplace_path(self):
        root = Path("/home/ubuntu/.claude/plugins/cache/sag-agents-marketplace/sag-agents/0.1.0")
        warning = self.mod._versioned_install_warning(root)
        self.assertIn("/home/ubuntu/.claude/plugins/marketplaces", warning.replace("\\", "/"))

    def test_marketplace_checkout_does_not_warn(self):
        root = Path("/home/ubuntu/.claude/plugins/marketplaces/sag-agents-marketplace")
        self.assertIsNone(self.mod._versioned_install_warning(root))

    def test_plain_git_clone_does_not_warn(self):
        self.assertIsNone(self.mod._versioned_install_warning(Path("/home/ubuntu/sag-agents-plugin")))


if __name__ == "__main__":
    unittest.main()
