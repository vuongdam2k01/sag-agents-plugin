"""Gate extensions for SPEC A3: the git clause is conditional, and an undecodable
file gets UNSCANNABLE (routed to a human) instead of being certified unscanned.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _bootstrap  # noqa: F401

from sagctl import gate
from sagctl import manifest as manifest_mod


def base_manifest(**overrides):
    return {**manifest_mod.DEFAULTS, "source_id": "abc", **overrides}


class TestSecretScanHonesty(unittest.TestCase):
    def test_undecodable_bytes_are_unscannable_not_clean(self):
        """The bug this replaces: reading with errors="replace" and reporting
        'clean' for a file it never actually read."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.pdf"
            p.write_bytes(b"%PDF-1.4\x00\xff\xfe\x00binary garbage not utf-8 \x80\x81")
            r = gate.check_secret_scan(p)
            self.assertFalse(r.ok)
            self.assertEqual(r.code, "UNSCANNABLE")

    def test_plain_text_with_no_secret_passes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.md"
            p.write_text("# Title\n\nJust some notes.\n", encoding="utf-8")
            r = gate.check_secret_scan(p)
            self.assertTrue(r.ok)

    def test_text_containing_a_secret_is_a_hard_reject_not_unscannable(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.md"
            p.write_text('api_key: "not-a-real-secret-0123456789ab"\n', encoding="utf-8")
            r = gate.check_secret_scan(p)
            self.assertFalse(r.ok)
            self.assertEqual(r.code, "SECRET_FOUND")

    def test_check_secret_scan_text_is_the_shared_implementation(self):
        r = gate.check_secret_scan_text("nothing interesting here")
        self.assertTrue(r.ok)


class TestCheckFloorGitOptional(unittest.TestCase):
    def test_in_git_repo_false_skips_the_git_clause_entirely(self):
        """The whole point: outside a repo the git clause is inapplicable, not
        bypassed as a favour — check_git_state must never even run."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "notes.md"
            p.write_text("clean content\n", encoding="utf-8")
            m = base_manifest(require="committed")
            with mock.patch.object(gate, "check_git_state") as git_check:
                r = gate.check_floor(
                    file_path=p, repo_root=Path(td), relpath="notes.md", key="notes.md",
                    manifest=m, source_id="src", in_git_repo=False,
                )
            git_check.assert_not_called()
            self.assertTrue(r.ok)

    def test_in_git_repo_true_still_runs_the_git_clause(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "notes.md"
            p.write_text("clean content\n", encoding="utf-8")
            m = base_manifest(require="committed")
            with mock.patch.object(gate, "check_git_state") as git_check:
                git_check.return_value = gate.GateResult(True, code="OK")
                gate.check_floor(
                    file_path=p, repo_root=Path(td), relpath="notes.md", key="notes.md",
                    manifest=m, source_id="src", in_git_repo=True,
                )
            git_check.assert_called_once()

    def test_deny_paths_still_blocks_outside_a_repo(self):
        """A3 removes the git precondition, not the rest of the floor."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pricing" / "x.md"
            p.parent.mkdir()
            p.write_text("clean\n", encoding="utf-8")
            m = base_manifest(deny_paths=["pricing/**"])
            r = gate.check_floor(
                file_path=p, repo_root=Path(td), relpath="pricing/x.md", key="pricing__x.md",
                manifest=m, source_id="src", in_git_repo=False,
            )
            self.assertFalse(r.ok)
            self.assertEqual(r.code, "DENIED_PATH")


class TestCheckFloorContent(unittest.TestCase):
    def test_clean_authored_text_passes(self):
        m = base_manifest()
        r = gate.check_floor_content(
            relpath="research/notes.md", key="research__notes.md", manifest=m,
            source_id="src", text="just a synthesis, nothing sensitive",
        )
        self.assertTrue(r.ok)

    def test_secret_in_authored_text_is_rejected(self):
        m = base_manifest()
        r = gate.check_floor_content(
            relpath="research/notes.md", key="research__notes.md", manifest=m,
            source_id="src", text='api_key: "not-a-real-secret-0123456789ab"',
        )
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "SECRET_FOUND")

    def test_deny_paths_applies_to_the_chosen_relpath(self):
        m = base_manifest(deny_paths=["pricing/**"])
        r = gate.check_floor_content(
            relpath="pricing/notes.md", key="pricing__notes.md", manifest=m,
            source_id="src", text="clean",
        )
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "DENIED_PATH")

    def test_not_included_applies_to_the_chosen_relpath(self):
        m = base_manifest(include=["research/**"])
        r = gate.check_floor_content(
            relpath="other/notes.md", key="other__notes.md", manifest=m,
            source_id="src", text="clean",
        )
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "NOT_INCLUDED")


if __name__ == "__main__":
    unittest.main()
