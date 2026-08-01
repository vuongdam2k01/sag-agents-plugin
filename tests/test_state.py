"""State backend tests (SPEC S1 amendment A1).

The HTTP tests run against a REAL in-process sagstate server on an ephemeral
port — not a mock. The whole point of the amendment is cross-host behaviour, and
a mock of the thing under test would prove nothing about it.
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from sagctl import config as config_mod
from sagctl import state as state_mod

import sagstate_server


class _LocalBackendBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SAGCTL_HOME"] = self._tmp.name
        os.environ.pop("SAGCTL_STATE_URL", None)
        os.environ.pop("SAGCTL_STATE_TOKEN", None)
        state_mod.reset_backend()

    def tearDown(self):
        state_mod.reset_backend()
        os.environ.pop("SAGCTL_HOME", None)
        self._tmp.cleanup()


class TestBackendSelection(_LocalBackendBase):
    def test_defaults_to_local(self):
        self.assertEqual(state_mod.get_backend().name, "local")

    def test_state_url_selects_http(self):
        os.environ["SAGCTL_STATE_URL"] = "http://example.invalid:9000"
        state_mod.reset_backend()
        self.assertEqual(state_mod.get_backend().name, "http")

    def test_unexpanded_placeholder_falls_back_to_local(self):
        """An agent tool that does not substitute an unset ${VAR} must not send the
        engine chasing a nonsense URL — adapters declare the var so it reaches sagw."""
        os.environ["SAGCTL_STATE_URL"] = "${SAGCTL_STATE_URL}"
        state_mod.reset_backend()
        self.assertEqual(state_mod.get_backend().name, "local")

    def test_blank_state_url_falls_back_to_local(self):
        os.environ["SAGCTL_STATE_URL"] = "   "
        state_mod.reset_backend()
        self.assertEqual(state_mod.get_backend().name, "local")

    def test_unexpanded_token_placeholder_is_treated_as_no_token(self):
        os.environ["SAGCTL_STATE_URL"] = "http://example.invalid:9000"
        os.environ["SAGCTL_STATE_TOKEN"] = "${SAGCTL_STATE_TOKEN}"
        state_mod.reset_backend()
        self.assertIsNone(state_mod.get_backend().token)

    def test_source_key_is_what_reaches_the_wire(self):
        """A real source_id must never end up in a URL, an access log, or a proxy trace."""
        backend = state_mod.HttpBackend("http://example.invalid:9000")
        skey = backend._skey("project-a-knowledge")
        self.assertNotIn("project-a-knowledge", skey)
        self.assertEqual(skey, config_mod.source_key("project-a-knowledge"))
        self.assertEqual(len(skey), 12)


class TestLocalBackend(_LocalBackendBase):
    def test_audit_roundtrip(self):
        state_mod.audit_append("src-a", {"event": "published", "key": "a.md"})
        state_mod.audit_append("src-a", {"event": "published", "key": "b.md"})
        records = state_mod.audit_read("src-a")
        self.assertEqual([r["key"] for r in records], ["a.md", "b.md"])

    def test_audit_is_isolated_per_source(self):
        state_mod.audit_append("src-a", {"event": "x"})
        self.assertEqual(state_mod.audit_read("src-b"), [])

    def test_cost_bump_accumulates(self):
        state_mod.cost_bump("src-a", "k.md")
        data = state_mod.cost_bump("src-a", "k.md")
        self.assertEqual(data["publishes"], 2)
        self.assertEqual(data["per_key"]["k.md"], 2)

    def test_cost_rolls_over_on_a_new_day(self):
        state_mod.cost_bump("src-a", "k.md")
        stale = config_mod.cost_path("src-a")
        stale.write_text('{"day": "1999-01-01", "publishes": 99, "per_key": {"k.md": 99}}', encoding="utf-8")
        data = state_mod.cost_bump("src-a", "k.md")
        self.assertEqual(data["publishes"], 1)
        self.assertEqual(data["day"], state_mod.today_utc())

    def test_cost_survives_a_corrupt_file(self):
        config_mod.cost_path("src-a").write_text("{not json", encoding="utf-8")
        self.assertEqual(state_mod.cost_get("src-a")["publishes"], 0)

    def test_queue_add_and_list(self):
        state_mod.queue_add("src-a", {"id": "q1", "status": "pending", "key": "a.md"})
        state_mod.queue_add("src-a", {"id": "q2", "status": "pending", "key": "b.md"})
        self.assertEqual([i["id"] for i in state_mod.queue_list("src-a")], ["q1", "q2"])

    def test_queue_set_status_is_compare_and_set(self):
        state_mod.queue_add("src-a", {"id": "q1", "status": "pending", "key": "a.md"})
        item = state_mod.queue_set_status("src-a", "q1", "approved", "reviewer-1")
        self.assertEqual(item["status"], "approved")
        self.assertEqual(item["reviewed_by"], "reviewer-1")
        # A second approval must lose — this is what stops two hosts double-publishing.
        with self.assertRaises(state_mod.QueueItemNotPending):
            state_mod.queue_set_status("src-a", "q1", "approved", "reviewer-2")

    def test_queue_set_status_unknown_id(self):
        with self.assertRaises(state_mod.StateError):
            state_mod.queue_set_status("src-a", "nope", "approved", "r")

    def test_lock_is_released_after_use(self):
        state_mod.cost_bump("src-a", "k.md")
        lock = config_mod.source_dir("src-a") / ".cost.lock"
        self.assertFalse(lock.exists())


class TestHttpBackendAgainstRealServer(unittest.TestCase):
    """Two HttpBackend instances = two agent hosts pointed at one state service."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.token = "test-shared-secret"
        cls.server = sagstate_server.build_server("127.0.0.1", 0, Path(cls._tmp.name), cls.token)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def _host(self):
        return state_mod.HttpBackend(self.url, self.token)

    def test_rejects_a_missing_token(self):
        anon = state_mod.HttpBackend(self.url, None)
        with self.assertRaises(state_mod.StateError) as ctx:
            anon.audit_read("src-auth")
        self.assertIn("401", str(ctx.exception))

    def test_rejects_a_wrong_token(self):
        wrong = state_mod.HttpBackend(self.url, "not-the-secret")
        with self.assertRaises(state_mod.StateError):
            wrong.audit_read("src-auth")

    def test_two_hosts_share_one_audit_log(self):
        host_a, host_b = self._host(), self._host()
        host_a.audit_append("src-shared", {"event": "published", "agent": "claude-code"})
        host_b.audit_append("src-shared", {"event": "published", "agent": "hermes:dev"})
        agents = [r["agent"] for r in host_a.audit_read("src-shared")]
        self.assertEqual(agents, ["claude-code", "hermes:dev"])

    def test_two_hosts_share_one_cost_counter(self):
        """The whole reason the amendment exists: the cap is a fleet budget, not a per-host one."""
        host_a, host_b = self._host(), self._host()
        host_a.cost_bump("src-cost", "a.md")
        data = host_b.cost_bump("src-cost", "b.md")
        self.assertEqual(data["publishes"], 2)
        self.assertEqual(host_a.cost_get("src-cost")["publishes"], 2)

    def test_queue_item_from_one_host_is_approvable_from_another(self):
        host_a, host_b = self._host(), self._host()
        host_a.queue_add("src-queue", {"id": "q-cross", "status": "pending", "key": "a.md"})
        pending = [i["id"] for i in host_b.queue_list("src-queue")]
        self.assertIn("q-cross", pending)
        item = host_b.queue_set_status("src-queue", "q-cross", "approved", "reviewer-on-host-b")
        self.assertEqual(item["status"], "approved")

    def test_concurrent_approval_from_two_hosts_yields_exactly_one_winner(self):
        host_a, host_b = self._host(), self._host()
        host_a.queue_add("src-race", {"id": "q-race", "status": "pending", "key": "a.md"})
        results = []

        def approve(host, who):
            try:
                host.queue_set_status("src-race", "q-race", "approved", who)
                results.append(("ok", who))
            except state_mod.QueueItemNotPending:
                results.append(("conflict", who))

        threads = [
            threading.Thread(target=approve, args=(host_a, "a")),
            threading.Thread(target=approve, args=(host_b, "b")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        outcomes = sorted(r[0] for r in results)
        self.assertEqual(outcomes, ["conflict", "ok"])

    def test_concurrent_cost_bumps_do_not_lose_updates(self):
        hosts = [self._host() for _ in range(4)]
        threads = [
            threading.Thread(target=lambda h=h, i=i: [h.cost_bump("src-concurrent", f"k{i}.md") for _ in range(10)])
            for i, h in enumerate(hosts)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        self.assertEqual(hosts[0].cost_get("src-concurrent")["publishes"], 40)

    def test_unknown_route_is_404_not_a_crash(self):
        host = self._host()
        with self.assertRaises(state_mod.StateError) as ctx:
            host._call("GET", "/v1/000000000000/nonsense")
        self.assertIn("404", str(ctx.exception))

    def test_malformed_source_key_is_rejected(self):
        host = self._host()
        with self.assertRaises(state_mod.StateError) as ctx:
            host._call("GET", "/v1/not-a-valid-key/audit")
        self.assertIn("400", str(ctx.exception))

    def test_unreachable_service_raises_state_error_not_a_raw_socket_error(self):
        """Same lesson as restclient.py — an unwrapped network error kills the publish."""
        dead = state_mod.HttpBackend("http://127.0.0.1:1", "tok", timeout=2.0)
        with self.assertRaises(state_mod.StateError):
            dead.audit_read("src-dead")


class TestAuditAndQueueThroughTheBackend(_LocalBackendBase):
    """The public API of audit.py / queue.py must be unchanged by the refactor."""

    def test_audit_append_stamps_ts(self):
        from sagctl import audit

        audit.append("src-a", {"event": "published", "key": "a.md"})
        records = audit.read_all("src-a")
        self.assertEqual(len(records), 1)
        self.assertIn("ts", records[0])
        self.assertEqual(records[0]["event"], "published")

    def test_check_cost_cap_blocks_at_the_manifest_limit(self):
        from sagctl import audit

        manifest = {"max_publishes_per_day": 3}
        for _ in range(3):
            audit.bump_cost_counter("src-a", "k.md")
        ok, reason = audit.check_cost_cap("src-a", manifest, "other.md")
        self.assertFalse(ok)
        self.assertIn("max_publishes_per_day", reason)

    def test_check_cost_cap_blocks_a_republish_loop(self):
        from sagctl import audit

        for _ in range(5):
            audit.bump_cost_counter("src-a", "loop.md")
        ok, reason = audit.check_cost_cap("src-a", {"max_publishes_per_day": 999}, "loop.md")
        self.assertFalse(ok)
        self.assertIn("republish loop", reason)

    def test_queue_enqueue_list_and_reject(self):
        from sagctl import queue as queue_mod

        item = queue_mod.enqueue(
            "src-a",
            path="/repo/docs/a.md",
            key="docs__a.md",
            relpath="docs/a.md",
            assessment=None,
            reason="below threshold",
            agent="claude-code",
        )
        self.assertEqual([i["id"] for i in queue_mod.list_pending("src-a")], [item["id"]])
        queue_mod.reject("src-a", item["id"], reviewer="me", reason="not knowledge")
        self.assertEqual(queue_mod.list_pending("src-a"), [])
        self.assertEqual(queue_mod.find("src-a", item["id"])["status"], "rejected")

    def test_double_review_raises_queue_error(self):
        from sagctl import queue as queue_mod

        item = queue_mod.enqueue(
            "src-a",
            path="/repo/docs/a.md",
            key="docs__a.md",
            relpath="docs/a.md",
            assessment=None,
            reason="r",
            agent="claude-code",
        )
        queue_mod.reject("src-a", item["id"], reviewer="me", reason="no")
        with self.assertRaises(queue_mod.QueueError):
            queue_mod.reject("src-a", item["id"], reviewer="me2", reason="no again")


if __name__ == "__main__":
    unittest.main()
