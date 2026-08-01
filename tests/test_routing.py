import unittest

import _bootstrap  # noqa: F401
from sagctl import manifest as manifest_mod
from sagctl import routing


def base_manifest(**overrides):
    return {**manifest_mod.DEFAULTS, "source_id": "abc", **overrides}


class TestRouting(unittest.TestCase):
    def test_deny_path_wins_over_everything(self):
        m = base_manifest(deny_paths=["docs/pricing/**"])
        assessment = {"verdict": "knowledge", "confidence": 0.99}
        d = routing.decide(relpath="docs/pricing/x.md", manifest=m, assessment=assessment, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.REJECT_DENY)

    def test_deny_path_blocks_manual_too(self):
        m = base_manifest(deny_paths=["docs/pricing/**"])
        d = routing.decide(relpath="docs/pricing/x.md", manifest=m, assessment=None, manual_token_valid=True)
        self.assertEqual(d.route, routing.Route.REJECT_DENY)

    def test_manual_bypasses_assessment(self):
        m = base_manifest()
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=None, manual_token_valid=True)
        self.assertEqual(d.route, routing.Route.MANUAL)

    def test_manual_still_respects_include(self):
        m = base_manifest(include=["docs/**/*.md"])
        d = routing.decide(relpath="other/x.md", manifest=m, assessment=None, manual_token_valid=True)
        self.assertEqual(d.route, routing.Route.REJECT_NOT_INCLUDED)

    def test_no_assessment_no_manual_queues(self):
        m = base_manifest()
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=None, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.QUEUE)

    def test_not_knowledge_rejected(self):
        m = base_manifest()
        a = {"verdict": "not-knowledge", "confidence": 0.9}
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.REJECT_NOT_KNOWLEDGE)

    def test_ask_paths_forces_queue_even_high_confidence(self):
        m = base_manifest(ask_paths=["docs/sensitive/**"])
        a = {"verdict": "knowledge", "confidence": 0.99}
        d = routing.decide(relpath="docs/sensitive/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.QUEUE)

    def test_criteria_present_but_ack_empty_queues(self):
        m = base_manifest(criteria=[{"id": "c1", "text": "no meeting notes"}])
        a = {"verdict": "knowledge", "confidence": 0.95, "criteria_ack": []}
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.QUEUE)

    def test_criteria_present_and_acked_autos(self):
        m = base_manifest(criteria=[{"id": "c1", "text": "no meeting notes"}], min_confidence=0.8)
        a = {"verdict": "knowledge", "confidence": 0.95, "criteria_ack": ["c1"]}
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.AUTO)

    def test_criteria_ack_with_fabricated_ids_queues_not_autos(self):
        """'criteria_ack has teeth' means real ids, not merely a non-empty list.
        Found by review, 2026-08-01: the previous check only tested `not ack`, so
        any non-empty criteria_ack passed regardless of whether its ids existed
        anywhere in the manifest — an agent (or a bug) could fabricate an id and
        sail straight to AUTO."""
        m = base_manifest(criteria=[{"id": "c1", "text": "no meeting notes"}], min_confidence=0.8)
        a = {"verdict": "knowledge", "confidence": 0.95, "criteria_ack": ["totally-made-up-id"]}
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.QUEUE)

    def test_criteria_ack_with_one_real_and_one_fake_id_still_autos(self):
        """Partial-but-real coverage is enough — the check is "did you engage with
        the real criteria at all", not "did you enumerate every single one"."""
        m = base_manifest(
            criteria=[{"id": "c1", "text": "no meeting notes"}, {"id": "c2", "text": "no PII"}],
            min_confidence=0.8,
        )
        a = {"verdict": "knowledge", "confidence": 0.95, "criteria_ack": ["c1", "unknown-id"]}
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.AUTO)

    def test_confidence_below_threshold_queues(self):
        m = base_manifest(min_confidence=0.8)
        a = {"verdict": "knowledge", "confidence": 0.5}
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.QUEUE)

    def test_unsure_queues(self):
        m = base_manifest()
        a = {"verdict": "unsure", "confidence": 0.99}
        d = routing.decide(relpath="docs/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.QUEUE)

    def test_exclude_wins_over_include(self):
        m = base_manifest(include=["**/*.md"], exclude=["docs/drafts/**"])
        a = {"verdict": "knowledge", "confidence": 0.95}
        d = routing.decide(relpath="docs/drafts/x.md", manifest=m, assessment=a, manual_token_valid=False)
        self.assertEqual(d.route, routing.Route.REJECT_NOT_INCLUDED)


if __name__ == "__main__":
    unittest.main()
