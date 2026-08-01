"""Pluggable state backend for audit / queue / cost counters (SPEC S1 amendment A1).

SPEC S1 places audit/queue/cost under `~/.sagctl/<sha256(source_id)[:12]>/`. The
requirement that produced that location is "an agent inside the workspace must not
be able to write it" (REVIEW-OPUS F5) — which demands *not agent-writable*, NOT
*local disk*. On one machine the two coincide. Across a fleet where each agent runs
on its own host they do not:

- every host keeps its own cost counter  => `max_publishes_per_day` multiplies by host count
- every host keeps its own queue         => an item queued on host A can never be approved from host B
- every host keeps its own audit         => `doctor` / `review-self-gate` see a fraction of the history

This module puts all of those accesses behind a backend, so the same engine either
keeps the local files (default, behaviour unchanged) or points the whole fleet at
one shared state service via `SAGCTL_STATE_URL`.

Every operation here is atomic by construction. There is deliberately no
`cost_set()` / `queue_save()`: two hosts doing GET-then-PUT on a counter is a lost
update, and the whole point of this module is that the fleet shares one counter.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config


class StateError(RuntimeError):
    pass


class QueueItemNotPending(StateError):
    """CAS failure — the item was already approved/rejected (possibly by another host)."""


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def empty_cost() -> dict:
    return {"day": today_utc(), "publishes": 0, "per_key": {}}


def _parse_jsonl(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn line never invalidates the rest of the log
    return out


# --------------------------------------------------------------------------
# local backend
# --------------------------------------------------------------------------


class _FileLock:
    """Advisory lock via atomic O_EXCL create — no fcntl (POSIX-only) and no
    msvcrt (Windows-only), so one implementation covers both.

    Only wraps read-modify-write sequences (cost bump, queue status change).
    Two processes racing on the same host is a real case, not a hypothetical:
    Claude Code's PostToolUse hook, the `sagw` MCP server, and a CLI invocation
    are three separate processes sharing one `~/.sagctl/`.
    """

    def __init__(self, path: Path, timeout: float = 10.0):
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                # Break a stale lock: a crashed holder must not wedge the engine forever.
                try:
                    if time.time() - self.path.stat().st_mtime > self.timeout:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise StateError(f"timed out acquiring lock {self.path}") from None
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.path.unlink(missing_ok=True)
        return False


class LocalBackend:
    """The pre-A1 behaviour, byte-for-byte compatible with existing ~/.sagctl/ files.

    No migration step: a fleet that never sets SAGCTL_STATE_URL sees no change.
    """

    name = "local"

    def _lock(self, source_id: str, what: str) -> _FileLock:
        return _FileLock(config.source_dir(source_id) / f".{what}.lock")

    # -- audit --
    def audit_append(self, source_id: str, record: dict) -> None:
        path = config.audit_path(source_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def audit_read(self, source_id: str) -> list[dict]:
        path = config.audit_path(source_id)
        if not path.exists():
            return []
        return _parse_jsonl(path.read_text(encoding="utf-8"))

    # -- cost --
    def _cost_load(self, source_id: str) -> dict:
        path = config.cost_path(source_id)
        if not path.exists():
            return empty_cost()
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return empty_cost()

    def cost_get(self, source_id: str) -> dict:
        return self._cost_load(source_id)

    def cost_bump(self, source_id: str, key: str) -> dict:
        with self._lock(source_id, "cost"):
            data = self._cost_load(source_id)
            if data.get("day") != today_utc():
                data = empty_cost()
            data["publishes"] = data.get("publishes", 0) + 1
            data.setdefault("per_key", {})
            data["per_key"][key] = data["per_key"].get(key, 0) + 1
            config.cost_path(source_id).write_text(json.dumps(data), encoding="utf-8")
            return data

    # -- queue --
    def _queue_load(self, source_id: str) -> list[dict]:
        path = config.queue_path(source_id)
        if not path.exists():
            return []
        return _parse_jsonl(path.read_text(encoding="utf-8"))

    def _queue_save(self, source_id: str, items: list[dict]) -> None:
        path = config.queue_path(source_id)
        with path.open("w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def queue_list(self, source_id: str) -> list[dict]:
        return self._queue_load(source_id)

    def queue_add(self, source_id: str, item: dict) -> dict:
        with self._lock(source_id, "queue"):
            items = self._queue_load(source_id)
            items.append(item)
            self._queue_save(source_id, items)
            return item

    # -- provenance (SPEC A3) --
    def provenance_put(self, source_id: str, key: str, record: dict) -> dict:
        with self._lock(source_id, "prov"):
            data = self._prov_load(source_id)
            data[key] = record
            (config.source_dir(source_id) / "provenance.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            return record

    def provenance_get(self, source_id: str, key: str) -> dict | None:
        return self._prov_load(source_id).get(key)

    def _prov_load(self, source_id: str) -> dict:
        path = config.source_dir(source_id) / "provenance.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def queue_set_status(self, source_id: str, queue_id: str, status: str, reviewer: str) -> dict:
        with self._lock(source_id, "queue"):
            items = self._queue_load(source_id)
            for item in items:
                if item["id"] != queue_id:
                    continue
                if item["status"] != "pending":
                    raise QueueItemNotPending(
                        f"queue item {queue_id} is already in state '{item['status']}'"
                    )
                item["status"] = status
                item["reviewed_by"] = reviewer
                item["reviewed_at"] = time.time()
                self._queue_save(source_id, items)
                return item
            raise StateError(f"queue item {queue_id} not found")


# --------------------------------------------------------------------------
# http backend
# --------------------------------------------------------------------------


class HttpBackend:
    """Fleet-shared state over HTTP (`SAGCTL_STATE_URL`).

    The source is addressed by `sha256(source_id)[:12]` — the same namespace key
    the local layout uses — so a real source_id never lands in a URL, an access
    log, or a proxy trace.
    """

    name = "http"

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict | None:
        url = f"{self.base_url}{path}"
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                parsed = raw.decode("utf-8", errors="replace")
            if e.code == 409:
                raise QueueItemNotPending(str(parsed)) from None
            raise StateError(f"state service {method} {path} -> HTTP {e.code}: {parsed}") from None
        except urllib.error.URLError as e:
            raise StateError(f"state service unreachable ({method} {path}): {e.reason}") from None
        except TimeoutError as e:
            # Same lesson as restclient.py: a timeout mid-response-read is NOT
            # always wrapped into URLError by urllib. Leaving it unwrapped means
            # one transient blip kills the whole publish.
            raise StateError(f"state service timeout ({method} {path}): {e}") from None
        except ConnectionError as e:
            raise StateError(f"state service connection error ({method} {path}): {e}") from None

    def _skey(self, source_id: str) -> str:
        return config.source_key(source_id)

    def audit_append(self, source_id: str, record: dict) -> None:
        self._call("POST", f"/v1/{self._skey(source_id)}/audit", record)

    def audit_read(self, source_id: str) -> list[dict]:
        res = self._call("GET", f"/v1/{self._skey(source_id)}/audit")
        return (res or {}).get("records", [])

    def cost_get(self, source_id: str) -> dict:
        return self._call("GET", f"/v1/{self._skey(source_id)}/cost") or empty_cost()

    def cost_bump(self, source_id: str, key: str) -> dict:
        return self._call("POST", f"/v1/{self._skey(source_id)}/cost/bump", {"key": key}) or empty_cost()

    def queue_list(self, source_id: str) -> list[dict]:
        res = self._call("GET", f"/v1/{self._skey(source_id)}/queue")
        return (res or {}).get("items", [])

    def queue_add(self, source_id: str, item: dict) -> dict:
        return self._call("POST", f"/v1/{self._skey(source_id)}/queue", item) or item

    def queue_set_status(self, source_id: str, queue_id: str, status: str, reviewer: str) -> dict:
        return self._call(
            "POST",
            f"/v1/{self._skey(source_id)}/queue/{queue_id}/status",
            {"status": status, "reviewer": reviewer},
        )

    def provenance_put(self, source_id: str, key: str, record: dict) -> dict:
        return self._call(
            "POST", f"/v1/{self._skey(source_id)}/provenance", {"key": key, "record": record}
        ) or record

    def provenance_get(self, source_id: str, key: str) -> dict | None:
        res = self._call("POST", f"/v1/{self._skey(source_id)}/provenance/get", {"key": key})
        return (res or {}).get("record")


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

_backend = None


def _env(name: str) -> str | None:
    """Read an env var, treating an unexpanded `${VAR}` placeholder as unset.

    Adapter configs declare `SAGCTL_STATE_URL: "${SAGCTL_STATE_URL}"` so the value
    flows into the `sagw` subprocess. An agent tool that does not substitute an
    UNSET variable passes the literal placeholder through — without this guard the
    engine would read that as "http backend configured" and every publish would die
    against a nonsense URL instead of quietly using local state.
    """
    value = (os.environ.get(name) or "").strip()
    if not value or (value.startswith("${") and value.endswith("}")):
        return None
    return value


def get_backend():
    """Resolve the backend from the environment on first use.

    `SAGCTL_STATE_URL` unset => LocalBackend, i.e. nothing changes for anyone
    running the plugin on a single machine.
    """
    global _backend
    if _backend is None:
        url = _env("SAGCTL_STATE_URL")
        if url:
            _backend = HttpBackend(url, _env("SAGCTL_STATE_TOKEN"))
        else:
            _backend = LocalBackend()
    return _backend


def reset_backend() -> None:
    """Drop the cached backend — for tests and for a process that changes env mid-run."""
    global _backend
    _backend = None


def audit_append(source_id: str, record: dict) -> None:
    get_backend().audit_append(source_id, record)


def audit_read(source_id: str) -> list[dict]:
    return get_backend().audit_read(source_id)


def cost_get(source_id: str) -> dict:
    return get_backend().cost_get(source_id)


def cost_bump(source_id: str, key: str) -> dict:
    return get_backend().cost_bump(source_id, key)


def queue_list(source_id: str) -> list[dict]:
    return get_backend().queue_list(source_id)


def queue_add(source_id: str, item: dict) -> dict:
    return get_backend().queue_add(source_id, item)


def queue_set_status(source_id: str, queue_id: str, status: str, reviewer: str) -> dict:
    return get_backend().queue_set_status(source_id, queue_id, status, reviewer)


def provenance_put(source_id: str, key: str, record: dict) -> dict:
    """Provenance for documents whose bytes cannot carry it — binaries, and anything
    published without a Git commit behind it (SPEC A3). Before the shared state store
    existed there was nowhere durable to keep this: SAG's upload accepts no metadata
    (DESIGN §1.3, consequence 3)."""
    return get_backend().provenance_put(source_id, key, record)


def provenance_get(source_id: str, key: str) -> dict | None:
    return get_backend().provenance_get(source_id, key)
