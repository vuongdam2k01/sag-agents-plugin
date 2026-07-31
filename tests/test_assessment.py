import unittest

import _bootstrap  # noqa: F401
from sagctl import assessment as assessment_mod


def valid_assessment(**overrides):
    base = {
        "path": "docs/x.md",
        "source_id": "abc",
        "commit": "abcdef1",
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


class TestAssessmentEnrich(unittest.TestCase):
    def test_enrich_fills_engine_fields(self):
        a = valid_assessment()
        out = assessment_mod.enrich(
            a, initiator="agent-auto", trigger="end-of-task", agent="claude-code", key="docs/x.md", criteria_available=["c1"]
        )
        self.assertEqual(out["initiator"], "agent-auto")
        self.assertEqual(out["trigger"], "end-of-task")
        self.assertEqual(out["agent"], "claude-code")
        self.assertEqual(out["key"], "docs/x.md")
        self.assertEqual(out["criteria_available"], ["c1"])
        self.assertIn("assessed_at", out)
        self.assertEqual(out["criteria_ack"], [])

    def test_enrich_rejects_bad_initiator(self):
        with self.assertRaises(assessment_mod.AssessmentError):
            assessment_mod.enrich(
                valid_assessment(), initiator="agent-said-so", trigger="end-of-task", agent="x", key="k", criteria_available=[]
            )

    def test_enrich_rejects_bad_trigger(self):
        with self.assertRaises(assessment_mod.AssessmentError):
            assessment_mod.enrich(
                valid_assessment(), initiator="agent-auto", trigger="whenever", agent="x", key="k", criteria_available=[]
            )


if __name__ == "__main__":
    unittest.main()
