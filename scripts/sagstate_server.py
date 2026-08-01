#!/usr/bin/env python3
"""sagstate — the fleet-shared state service for audit / queue / cost (SPEC S1 amendment A1).

Why this exists: SPEC S1 put audit/queue/cost on the local filesystem to satisfy
"an agent in the workspace must not be able to write it" (REVIEW-OPUS F5). That
requirement is about WRITE REACH, not about disk. When every agent runs on its own
host — Claude Code on a laptop, Hermes on a build box, Codex somewhere else — local
files mean each host has a private cost counter, a private queue, and a private
audit log, so `max_publishes_per_day` multiplies by host count and an item queued
on one host can never be approved from another.

This service is deliberately dumb storage with atomic operations. It holds no
policy: the manifest still decides what may be published, `gate.py` still runs the
deterministic floor, `routing.py` still decides auto/queue/reject. Compromising
this service lets an attacker forge audit history and reset the cost counter — it
does NOT let them publish anything the floor would have rejected.

Run:
    SAGSTATE_TOKEN=<shared-secret> python scripts/sagstate_server.py --host 0.0.0.0 --port 9000

Every agent host then sets:
    SAGCTL_STATE_URL=http://<state-host>:9000
    SAGCTL_STATE_TOKEN=<shared-secret>

Stdlib only, same as the rest of the engine — no pip install on the state host.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

__version__ = "0.1.0"

# The source namespace key is sha256(source_id)[:12] produced by sagctl's
# config.source_key() — a real source_id therefore never appears in a URL,
# an access log, or a proxy trace.
SKEY_RE = re.compile(r"^[0-9a-f]{12}$")
# sagctl mints queue ids with secrets.token_hex(8), but the id is only ever
# matched against JSON records — it never reaches a filesystem path. So the
# constraint that matters is "no path separators, bounded length", not "hex".
QUEUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(skey: str) -> threading.Lock:
    with _locks_guard:
        if skey not in _locks:
            _locks[skey] = threading.Lock()
        return _locks[skey]


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _empty_cost() -> dict:
    return {"day": _today_utc(), "publishes": 0, "per_key": {}}


class Store:
    """One directory per source key, mirroring the local ~/.sagctl/ layout so the
    two backends stay recognisably the same shape on disk."""

    def __init__(self, home: Path):
        self.home = home
        self.home.mkdir(parents=True, exist_ok=True)

    def _dir(self, skey: str) -> Path:
        d = self.home / skey
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # -- audit (append-only) --
    def audit_append(self, skey: str, record: dict) -> None:
        path = self._dir(skey) / "audit.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def audit_read(self, skey: str) -> list[dict]:
        return self._read_jsonl(self._dir(skey) / "audit.jsonl")

    # -- cost --
    def cost_get(self, skey: str) -> dict:
        path = self._dir(skey) / "cost.json"
        if not path.exists():
            return _empty_cost()
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _empty_cost()

    def cost_bump(self, skey: str, key: str) -> dict:
        data = self.cost_get(skey)
        if data.get("day") != _today_utc():
            data = _empty_cost()
        data["publishes"] = data.get("publishes", 0) + 1
        data.setdefault("per_key", {})
        data["per_key"][key] = data["per_key"].get(key, 0) + 1
        (self._dir(skey) / "cost.json").write_text(json.dumps(data), encoding="utf-8")
        return data

    # -- queue --
    def queue_list(self, skey: str) -> list[dict]:
        return self._read_jsonl(self._dir(skey) / "queue.jsonl")

    def _queue_save(self, skey: str, items: list[dict]) -> None:
        path = self._dir(skey) / "queue.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def queue_add(self, skey: str, item: dict) -> dict:
        items = self.queue_list(skey)
        items.append(item)
        self._queue_save(skey, items)
        return item

    # -- provenance --
    def provenance_load(self, skey: str) -> dict:
        path = self._dir(skey) / "provenance.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def provenance_put(self, skey: str, key: str, record: dict) -> dict:
        data = self.provenance_load(skey)
        data[key] = record
        (self._dir(skey) / "provenance.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        return record

    def provenance_get(self, skey: str, key: str) -> dict | None:
        return self.provenance_load(skey).get(key)

    def queue_set_status(self, skey: str, queue_id: str, status: str, reviewer: str) -> dict:
        items = self.queue_list(skey)
        for item in items:
            if item.get("id") != queue_id:
                continue
            if item.get("status") != "pending":
                raise Conflict(f"queue item {queue_id} is already in state '{item.get('status')}'")
            item["status"] = status
            item["reviewed_by"] = reviewer
            item["reviewed_at"] = time.time()
            self._queue_save(skey, items)
            return item
        raise NotFound(f"queue item {queue_id} not found")


class Conflict(RuntimeError):
    pass


class NotFound(RuntimeError):
    pass


class Handler(BaseHTTPRequestHandler):
    server_version = f"sagstate/{__version__}"
    store: Store = None  # type: ignore[assignment]
    token: str | None = None

    # -- plumbing --

    def _send(self, status: int, payload: dict | None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authorized(self) -> bool:
        if not self.token:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        # Constant-time compare — this is a shared secret sitting on the network.
        return hmac.compare_digest(header[len("Bearer ") :], self.token)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("body is not valid JSON") from None
        if not isinstance(parsed, dict):
            raise ValueError("body must be a JSON object")
        return parsed

    def log_message(self, fmt, *args):
        # Default BaseHTTPRequestHandler logging writes to stderr with no
        # timestamp discipline; keep it, but never log the Authorization header.
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- routing --

    def _route(self, method: str):
        parts = [p for p in self.path.split("?")[0].strip("/").split("/") if p]
        if len(parts) < 3 or parts[0] != "v1":
            raise NotFound("unknown route")
        skey, resource = parts[1], parts[2]
        if not SKEY_RE.match(skey):
            raise ValueError("invalid source key (expected sha256(source_id)[:12])")
        rest = parts[3:]
        return method, skey, resource, rest

    def _dispatch(self, method: str):
        _, skey, resource, rest = self._route(method)
        store = self.store

        if resource == "audit":
            if method == "POST" and not rest:
                store.audit_append(skey, self._read_json())
                return 204, None
            if method == "GET" and not rest:
                return 200, {"records": store.audit_read(skey)}

        elif resource == "cost":
            if method == "GET" and not rest:
                return 200, store.cost_get(skey)
            if method == "POST" and rest == ["bump"]:
                key = self._read_json().get("key")
                if not key:
                    raise ValueError("'key' is required")
                with _lock_for(skey):
                    return 200, store.cost_bump(skey, key)

        elif resource == "provenance":
            if method == "POST" and not rest:
                body = self._read_json()
                key, record = body.get("key"), body.get("record")
                if not key or not isinstance(record, dict):
                    raise ValueError("'key' and object 'record' are required")
                with _lock_for(skey):
                    return 200, store.provenance_put(skey, key, record)
            if method == "POST" and rest == ["get"]:
                key = self._read_json().get("key")
                if not key:
                    raise ValueError("'key' is required")
                return 200, {"record": store.provenance_get(skey, key)}

        elif resource == "queue":
            if method == "GET" and not rest:
                return 200, {"items": store.queue_list(skey)}
            if method == "POST" and not rest:
                item = self._read_json()
                if not item.get("id"):
                    raise ValueError("queue item requires an 'id'")
                with _lock_for(skey):
                    return 200, store.queue_add(skey, item)
            if method == "POST" and len(rest) == 2 and rest[1] == "status":
                queue_id = rest[0]
                if not QUEUE_ID_RE.match(queue_id):
                    raise ValueError("invalid queue id")
                body = self._read_json()
                status, reviewer = body.get("status"), body.get("reviewer")
                if status not in ("approved", "rejected"):
                    raise ValueError("status must be 'approved' or 'rejected'")
                with _lock_for(skey):
                    return 200, store.queue_set_status(skey, queue_id, status, reviewer or "unknown")

        raise NotFound("unknown route")

    def _handle(self, method: str) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        try:
            status, payload = self._dispatch(method)
            self._send(status, payload)
        except Conflict as e:
            self._send(409, {"error": str(e)})
        except NotFound as e:
            self._send(404, {"error": str(e)})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 — a storage fault must not kill the server
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):  # noqa: N802
        self._handle("GET")

    def do_POST(self):  # noqa: N802
        self._handle("POST")


def build_server(host: str, port: int, home: Path, token: str | None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": Store(home), "token": token})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sagstate — fleet-shared audit/queue/cost service")
    parser.add_argument("--host", default=os.environ.get("SAGSTATE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SAGSTATE_PORT", "9000")))
    parser.add_argument(
        "--home",
        default=os.environ.get("SAGSTATE_HOME", str(Path.home() / ".sagstate")),
        help="directory holding the state files (default ~/.sagstate)",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("SAGSTATE_TOKEN")
    if not token:
        print(
            "WARNING: SAGSTATE_TOKEN is not set — the service will accept any caller.\n"
            "         Only acceptable when bound to 127.0.0.1 or behind a network the\n"
            "         whole agent fleet already trusts.",
            file=sys.stderr,
        )
    if not token and args.host not in ("127.0.0.1", "localhost", "::1"):
        print("REFUSING to bind a non-loopback address without SAGSTATE_TOKEN.", file=sys.stderr)
        return 2

    server = build_server(args.host, args.port, Path(args.home), token)
    print(f"sagstate {__version__} listening on http://{args.host}:{args.port} (home={args.home})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
