"""`sagctl setup probe` tests.

The property under test is the one that fails silently in production: probe must
report the `key_format` the INSTANCE implies, never the value baked in from sag.home.
Getting this wrong means keys stop matching and every publish adds a duplicate
instead of replacing.
"""
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

import _bootstrap  # noqa: F401

from sagctl import __main__ as cli
from sagctl import selftest
from sagctl.restclient import SagApiError


def _args(**kw):
    base = {"url": "http://sag.test", "token": "tok", "full": False}
    base.update(kw)
    return SimpleNamespace(**base)


def _run(args) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.cmd_setup_probe(args)
    return code, json.loads(buf.getvalue())


class TestSetupProbe(unittest.TestCase):
    def setUp(self):
        self.caps = {"max_upload_mb": 25, "search_strategy": "multi"}

    def _patch(self, *, s1_passed: bool):
        caps = mock.patch("sagctl.restclient.SagClient.capabilities", return_value=self.caps)
        s1 = mock.patch.object(
            selftest,
            "case_s1_filename_roundtrip",
            return_value=selftest.CaseResult("S1", True, s1_passed, "detail-from-instance"),
        )
        return caps, s1

    def test_reports_flat_when_the_instance_truncates_the_path(self):
        """The sag.home behaviour: S1 fails, so `path` is unusable and `flat` is right."""
        caps, s1 = self._patch(s1_passed=False)
        with caps, s1:
            code, out = _run(_args())
        self.assertEqual(code, 0)
        self.assertEqual(out["key_format"], "flat")
        self.assertEqual(out["suggested_manifest"]["key_format"], "flat")

    def test_reports_path_when_the_instance_preserves_it(self):
        """A different instance must NOT silently inherit sag.home's default."""
        caps, s1 = self._patch(s1_passed=True)
        with caps, s1:
            code, out = _run(_args())
        self.assertEqual(code, 0)
        self.assertEqual(out["key_format"], "path")
        self.assertEqual(out["suggested_manifest"]["key_format"], "path")

    def test_evidence_is_carried_through_not_summarised_away(self):
        caps, s1 = self._patch(s1_passed=False)
        with caps, s1:
            _, out = _run(_args())
        self.assertEqual(out["key_format_evidence"], "detail-from-instance")

    def test_unmeasured_values_are_labelled_unmeasured(self):
        """Without --full, replace strategy and MCP scoping are assumptions. They must
        say so rather than look like results."""
        caps, s1 = self._patch(s1_passed=False)
        with caps, s1:
            _, out = _run(_args())
        self.assertIn("not measured", out["replace_strategy_evidence"])
        self.assertIsNone(out["mcp_read_scoping"]["verified"])

    def test_full_run_measures_s4_and_s17(self):
        caps, s1 = self._patch(s1_passed=False)
        s4 = mock.patch.object(
            selftest, "case_s4_delete_semantics",
            return_value=selftest.CaseResult("S4", True, True, "delete is synchronous"),
        )
        s17 = mock.patch.object(
            selftest, "case_s17_mcp_read_scoping",
            return_value=selftest.CaseResult("S17", False, True, "no leak"),
        )
        with caps, s1, s4, s17:
            _, out = _run(_args(full=True))
        self.assertEqual(out["replace_strategy"], "delete_first")
        self.assertEqual(out["replace_strategy_evidence"], "delete is synchronous")
        self.assertTrue(out["mcp_read_scoping"]["verified"])

    def test_async_delete_flips_the_replace_strategy(self):
        caps, s1 = self._patch(s1_passed=False)
        s4 = mock.patch.object(
            selftest, "case_s4_delete_semantics",
            return_value=selftest.CaseResult("S4", True, False, "delete is async"),
        )
        s17 = mock.patch.object(
            selftest, "case_s17_mcp_read_scoping",
            return_value=selftest.CaseResult("S17", False, None, "inconclusive"),
        )
        with caps, s1, s4, s17:
            _, out = _run(_args(full=True))
        self.assertEqual(out["replace_strategy"], "upload_then_delete")

    def test_unreachable_instance_exits_nonzero_without_probing(self):
        caps = mock.patch(
            "sagctl.restclient.SagClient.capabilities",
            side_effect=SagApiError(0, "refused", "GET", "/api/v1/system/capabilities"),
        )
        s1 = mock.patch.object(selftest, "case_s1_filename_roundtrip")
        with caps, s1 as s1_mock:
            code, out = _run(_args())
        self.assertEqual(code, 3)
        self.assertFalse(out["reachable"])
        s1_mock.assert_not_called()  # nothing is created against an instance we cannot reach

    def test_suggested_manifest_leaves_policy_fields_empty(self):
        """deny_paths / ask_paths / criteria are policy — §S1 requires a separate
        reviewed commit. A scaffold must not pre-populate them."""
        caps, s1 = self._patch(s1_passed=False)
        with caps, s1:
            _, out = _run(_args())
        m = out["suggested_manifest"]
        self.assertEqual(m["deny_paths"], [])
        self.assertEqual(m["ask_paths"], [])
        self.assertEqual(m["criteria"], [])

    def test_suggested_manifest_does_not_invent_a_source_id(self):
        caps, s1 = self._patch(s1_passed=False)
        with caps, s1:
            _, out = _run(_args())
        self.assertIn("fill in", out["suggested_manifest"]["source_id"])


class TestSuggestedManifestIsValid(unittest.TestCase):
    def test_scaffold_passes_manifest_validation_once_a_source_id_is_filled_in(self):
        from sagctl import manifest as manifest_mod

        caps = mock.patch("sagctl.restclient.SagClient.capabilities", return_value={})
        s1 = mock.patch.object(
            selftest, "case_s1_filename_roundtrip",
            return_value=selftest.CaseResult("S1", True, False, "d"),
        )
        with caps, s1:
            _, out = _run(_args())
        m = {**manifest_mod.DEFAULTS, **out["suggested_manifest"]}
        m["source_id"] = "project-a-knowledge"
        manifest_mod.validate(m)  # raises if the scaffold is not a valid manifest


if __name__ == "__main__":
    unittest.main()
