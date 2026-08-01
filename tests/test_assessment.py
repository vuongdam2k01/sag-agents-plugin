import unittest

import _bootstrap  # noqa: F401
from sagctl import assessment as assessment_mod


def valid_assessment(**overrides):
    """What a model actually sends — matches the MCP tool's real schema, which
    never asks for 'path'/'source_id'/'commit' (those are engine-authoritative,
    see assessment.py's module docstring for why requiring them from the model
    was a live bug: a real agent submitted exactly this shape and was rejected
    for 'missing required field: path', a field the tool schema never told it
    to include and the engine never reads back from the model anyway)."""
    base = {
        "verdict": "knowledge",
        "durable": {"pass": True, "why": "..."},
        "audience": {"pass": True, "why": "..."},
        "retrieval_fit": {"pass": True, "why": "..."},
        "confidence": 0.9,
        "rationale": "because of reason X",
    }
    base.update(overrides)
    return base


class TestAssessmentValidation(unittest.TestCase):
    def test_valid_passes(self):
        self.assertEqual(assessment_mod.validate_model_input(valid_assessment()), [])

    def test_missing_path_source_id_commit_is_not_an_error(self):
        """Regression: these three used to be required and a real agent hit this
        exact failure, having to improvise a `git rev-parse HEAD` call just to
        satisfy a check whose answer the engine already had."""
        a = valid_assessment()
        self.assertNotIn("path", a)
        self.assertNotIn("source_id", a)
        self.assertNotIn("commit", a)
        self.assertEqual(assessment_mod.validate_model_input(a), [])

    def test_missing_field_reported(self):
        a = valid_assessment()
        del a["rationale"]
        errors = assessment_mod.validate_model_input(a)
        self.assertTrue(any("rationale" in e for e in errors))

    def test_bad_verdict_reported(self):
        errors = assessment_mod.validate_model_input(valid_assessment(verdict="maybe"))
        self.assertTrue(any("verdict" in e for e in errors))

    def test_confidence_out_of_range_reported(self):
        errors = assessment_mod.validate_model_input(valid_assessment(confidence=1.5))
        self.assertTrue(any("confidence" in e for e in errors))

    def test_durable_missing_subfields_reported(self):
        errors = assessment_mod.validate_model_input(valid_assessment(durable={"pass": True}))
        self.assertTrue(any("durable" in e for e in errors))

    def test_empty_rationale_reported(self):
        errors = assessment_mod.validate_model_input(valid_assessment(rationale="   "))
        self.assertTrue(any("rationale" in e for e in errors))

    def test_criteria_ack_must_be_list_of_str(self):
        errors = assessment_mod.validate_model_input(valid_assessment(criteria_ack=[1, 2]))
        self.assertTrue(any("criteria_ack" in e for e in errors))


def _enrich(a, **overrides):
    kwargs = dict(
        initiator="agent-auto", trigger="end-of-task", agent="claude-code", key="docs__x.md",
        path="docs/x.md", source_id="src-abc", commit="deadbeef", criteria_available=["c1"],
    )
    kwargs.update(overrides)
    return assessment_mod.enrich(a, **kwargs)


class TestAssessmentEnrich(unittest.TestCase):
    def test_enrich_fills_engine_fields(self):
        out = _enrich(valid_assessment())
        self.assertEqual(out["initiator"], "agent-auto")
        self.assertEqual(out["trigger"], "end-of-task")
        self.assertEqual(out["agent"], "claude-code")
        self.assertEqual(out["key"], "docs__x.md")
        self.assertEqual(out["criteria_available"], ["c1"])
        self.assertIn("assessed_at", out)
        self.assertEqual(out["criteria_ack"], [])

    def test_enrich_sets_path_source_id_commit_from_the_engine(self):
        out = _enrich(valid_assessment(), path="docs/real.md", source_id="src-real", commit="c0ffee")
        self.assertEqual(out["path"], "docs/real.md")
        self.assertEqual(out["source_id"], "src-real")
        self.assertEqual(out["commit"], "c0ffee")

    def test_enrich_overwrites_a_model_supplied_path_source_id_commit(self):
        """The engine's values win even if a model includes its own guesses for
        these fields — they are never trusted, same as initiator/key."""
        a = valid_assessment(path="made/up.md", source_id="not-the-real-source", commit="fabricated")
        out = _enrich(a, path="docs/real.md", source_id="src-real", commit="c0ffee")
        self.assertEqual(out["path"], "docs/real.md")
        self.assertEqual(out["source_id"], "src-real")
        self.assertEqual(out["commit"], "c0ffee")

    def test_enrich_accepts_a_null_commit_for_authored_content(self):
        out = _enrich(valid_assessment(), commit=None)
        self.assertIsNone(out["commit"])

    def test_enrich_rejects_bad_initiator(self):
        with self.assertRaises(assessment_mod.AssessmentError):
            _enrich(valid_assessment(), initiator="agent-said-so")

    def test_enrich_rejects_bad_trigger(self):
        with self.assertRaises(assessment_mod.AssessmentError):
            _enrich(valid_assessment(), trigger="whenever")


if __name__ == "__main__":
    unittest.main()
