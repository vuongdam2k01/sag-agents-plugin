"""publish_content() — agent-authored text, no file, no repo (SPEC A3).

Reject/queue paths are asserted to never touch the network at all: they must return
or raise before `_client_from_credentials` is called, the same guarantee `publish_one`
gives for `REJECT_DENY`/`REJECT_NOT_INCLUDED`/`QUEUE`. The AUTO path is exercised
against a fake SagClient — no real network, but the full upload/provenance/audit
sequence runs for real.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _bootstrap  # noqa: F401

from sagctl import audit, publish as publish_mod, queue as queue_mod, state


def _write_manifest(path: Path, **overrides) -> Path:
    doc = {"source_id": "src-content", **overrides}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


KNOWLEDGE_ASSESSMENT = {
    "path": "research/notes.md",
    "source_id": "src-content",
    "commit": None,
    "verdict": "knowledge",
    "durable": {"pass": True, "why": "stable synthesis"},
    "audience": {"pass": True, "why": "team-wide"},
    "retrieval_fit": {"pass": True, "why": "self-contained"},
    "confidence": 0.95,
    "rationale": "clear, durable, no PII",
}


class _StateBackedTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SAGCTL_HOME"] = self._tmp.name
        os.environ.pop("SAGCTL_STATE_URL", None)
        state.reset_backend()
        self._manifest_dir = tempfile.TemporaryDirectory()
        self.manifest_path = _write_manifest(Path(self._manifest_dir.name) / ".sag-sync.json")

    def tearDown(self):
        state.reset_backend()
        os.environ.pop("SAGCTL_HOME", None)
        self._tmp.cleanup()
        self._manifest_dir.cleanup()


class TestRejectPathsNeverTouchTheNetwork(_StateBackedTestCase):
    def test_deny_paths_raises_before_any_client_call(self):
        _write_manifest(self.manifest_path, deny_paths=["pricing/**"])
        with mock.patch.object(publish_mod, "_client_from_credentials") as client:
            with self.assertRaises(publish_mod.PublishError) as ctx:
                publish_mod.publish_content(
                    "pricing/notes.md", "clean text",
                    manifest_path=self.manifest_path,
                )
        self.assertEqual(ctx.exception.code, "DENIED_PATH")
        client.assert_not_called()

    def test_not_included_raises_before_any_client_call(self):
        _write_manifest(self.manifest_path, include=["research/**"])
        with mock.patch.object(publish_mod, "_client_from_credentials") as client:
            with self.assertRaises(publish_mod.PublishError) as ctx:
                publish_mod.publish_content(
                    "other/notes.md", "clean text",
                    manifest_path=self.manifest_path,
                )
        self.assertEqual(ctx.exception.code, "NOT_INCLUDED")
        client.assert_not_called()


class TestQueueing(_StateBackedTestCase):
    def test_no_assessment_queues_with_content_preserved(self):
        with mock.patch.object(publish_mod, "_client_from_credentials") as client:
            result = publish_mod.publish_content(
                "research/notes.md", "a draft synthesis",
                derived_from=["docs/report.pdf@abc123"],
                manifest_path=self.manifest_path,
                agent="hermes:researcher",
            )
        client.assert_not_called()
        self.assertEqual(result.status, "queued")

        pending = queue_mod.list_pending("src-content")
        self.assertEqual(len(pending), 1)
        item = pending[0]
        self.assertEqual(item["mode"], "content")
        self.assertEqual(item["content"], "a draft synthesis")
        self.assertEqual(item["derived_from"], ["docs/report.pdf@abc123"])
        self.assertEqual(item["manifest_path"], str(self.manifest_path))
        self.assertEqual(item["relpath"], "research/notes.md")

    def test_unscoped_secret_in_queued_content_is_not_pre_screened(self):
        """No-assessment items skip the floor entirely (same as publish_one) — the
        secret scan runs when the item is later approved, not at enqueue time."""
        with mock.patch.object(publish_mod, "_client_from_credentials") as client:
            result = publish_mod.publish_content(
                "research/notes.md", 'api_key: "not-a-real-secret-0123456789ab"',
                manifest_path=self.manifest_path,
            )
        client.assert_not_called()
        self.assertEqual(result.status, "queued")


class TestFloorFailureAborts(_StateBackedTestCase):
    def test_secret_in_authored_text_raises_and_never_touches_the_network(self):
        with mock.patch.object(publish_mod, "_client_from_credentials") as client:
            with self.assertRaises(publish_mod.PublishError) as ctx:
                publish_mod.publish_content(
                    "research/notes.md", 'api_key: "not-a-real-secret-0123456789ab"',
                    assessment=KNOWLEDGE_ASSESSMENT,
                    manifest_path=self.manifest_path,
                )
        self.assertEqual(ctx.exception.code, "SECRET_FOUND")
        client.assert_not_called()

        records = audit.read_all("src-content")
        self.assertTrue(any(r["event"] == "publish_rejected_floor" for r in records))


class _FakeSagClient:
    def __init__(self):
        self.uploaded = []

    def list_documents_all(self, source_id):
        return [], False

    def upload_document(self, source_id, key, content_bytes):
        self.uploaded.append((source_id, key, content_bytes))
        return {"id": "doc-1", "filename": key}

    def delete_document(self, source_id, document_id, tolerate_404=True):
        return True


class TestAutoPublishRecordsProvenanceAndAudit(_StateBackedTestCase):
    def test_auto_publish_records_authored_provenance_and_audit(self):
        fake = _FakeSagClient()
        with mock.patch.object(publish_mod, "_client_from_credentials", return_value=fake):
            result = publish_mod.publish_content(
                "research/notes.md",
                "# Pricing research\n\nCompetitors charge $X.\n",
                assessment=KNOWLEDGE_ASSESSMENT,
                derived_from=["docs/report.pdf@abc123"],
                manifest_path=self.manifest_path,
                agent="hermes:researcher",
            )
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.route, "auto")
        self.assertEqual(len(fake.uploaded), 1)

        prov = state.provenance_get("src-content", result.key)
        self.assertIsNotNone(prov)
        self.assertIsNone(prov["sag_source_commit"])
        self.assertIsNone(prov["sag_source_blob"])
        self.assertFalse(prov["sag_in_git"])
        self.assertTrue(prov["sag_authored"])
        self.assertEqual(prov["sag_derived_from"], ["docs/report.pdf@abc123"])

        published = [r for r in audit.read_all("src-content") if r["event"] == "published"]
        self.assertEqual(len(published), 1)
        self.assertIsNone(published[0]["commit"])
        self.assertEqual(published[0]["agent"], "hermes:researcher")

    def test_uploaded_bytes_carry_frontmatter_for_markdown_relpaths(self):
        fake = _FakeSagClient()
        with mock.patch.object(publish_mod, "_client_from_credentials", return_value=fake):
            publish_mod.publish_content(
                "research/notes.md", "# Title\n\nBody.\n",
                assessment=KNOWLEDGE_ASSESSMENT, manifest_path=self.manifest_path,
            )
        _, _, uploaded_bytes = fake.uploaded[0]
        self.assertTrue(uploaded_bytes.decode("utf-8").startswith("---\n"))

    def test_uploaded_bytes_are_raw_for_non_frontmatter_relpaths(self):
        fake = _FakeSagClient()
        with mock.patch.object(publish_mod, "_client_from_credentials", return_value=fake):
            publish_mod.publish_content(
                "research/notes.json", '{"a": 1}',
                assessment=KNOWLEDGE_ASSESSMENT, manifest_path=self.manifest_path,
            )
        _, _, uploaded_bytes = fake.uploaded[0]
        self.assertEqual(uploaded_bytes, b'{"a": 1}')


class TestQueueApproveDispatchesByMode(_StateBackedTestCase):
    def test_content_mode_item_is_approved_via_publish_content_not_publish_one(self):
        item = queue_mod.enqueue(
            "src-content",
            path="authored:research/notes.md",
            key="research__notes.md",
            relpath="research/notes.md",
            assessment=KNOWLEDGE_ASSESSMENT,
            reason="below threshold",
            agent="hermes:researcher",
            content="a synthesis",
            derived_from=["docs/report.pdf@abc123"],
            manifest_path=str(self.manifest_path),
        )
        fake_result = publish_mod.PublishResult(status="pending", key="research__notes.md", route="auto")
        with mock.patch.object(publish_mod, "publish_content", return_value=fake_result) as pc:
            with mock.patch.object(publish_mod, "publish_one") as po:
                queue_mod.approve("src-content", item["id"], reviewer="me")
        pc.assert_called_once()
        po.assert_not_called()
        called_args, called_kwargs = pc.call_args
        self.assertEqual(called_args[0], "research/notes.md")
        self.assertEqual(called_args[1], "a synthesis")
        self.assertEqual(called_kwargs["derived_from"], ["docs/report.pdf@abc123"])

    def test_file_mode_item_still_dispatches_to_publish_one(self):
        item = queue_mod.enqueue(
            "src-content", path="/repo/docs/a.md", key="docs__a.md", relpath="docs/a.md",
            assessment=None, reason="r", agent="claude-code",
        )
        self.assertEqual(item["mode"], "file")
        fake_result = publish_mod.PublishResult(status="pending", key="docs__a.md", route="auto")
        with mock.patch.object(publish_mod, "publish_one", return_value=fake_result) as po:
            with mock.patch.object(publish_mod, "publish_content") as pc:
                queue_mod.approve("src-content", item["id"], reviewer="me")
        po.assert_called_once()
        pc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
