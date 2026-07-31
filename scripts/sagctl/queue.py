"""Proposal queue — lives at ~/.sagctl/, NOT in the repo (SPEC S1, REVIEW-OPUS
§2c: '.sag/queue.jsonl in the repo = agent approving its own queue').

approve/reject is the `queue-review` op — per SPEC S8 it must be explicitly
enabled, granted only to reviewer/orchestrator, and is not part of default ops.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from . import audit, config


class QueueError(RuntimeError):
    pass


def _load(source_id: str) -> list[dict]:
    path = config.queue_path(source_id)
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _save(source_id: str, items: list[dict]) -> None:
    path = config.queue_path(source_id)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def enqueue(source_id: str, *, path: str, key: str, relpath: str, assessment: dict | None, reason: str, agent: str) -> dict:
    item = {
        "id": secrets.token_hex(8),
        "source_id": source_id,
        "path": path,
        "key": key,
        "relpath": relpath,
        "assessment": assessment,
        "reason": reason,
        "agent": agent,
        "status": "pending",
        "created_at": time.time(),
    }
    items = _load(source_id)
    items.append(item)
    _save(source_id, items)
    audit.append(source_id, {"event": "queued", "queue_id": item["id"], "key": key, "reason": reason, "agent": agent})
    return item


def list_pending(source_id: str) -> list[dict]:
    return [i for i in _load(source_id) if i["status"] == "pending"]


def find(source_id: str, queue_id: str) -> dict | None:
    for item in _load(source_id):
        if item["id"] == queue_id:
            return item
    return None


def _update_status(source_id: str, queue_id: str, status: str, *, reviewer: str) -> dict:
    items = _load(source_id)
    for item in items:
        if item["id"] == queue_id:
            if item["status"] != "pending":
                raise QueueError(f"queue item {queue_id} is already in state '{item['status']}'")
            item["status"] = status
            item["reviewed_by"] = reviewer
            item["reviewed_at"] = time.time()
            _save(source_id, items)
            return item
    raise QueueError(f"queue item {queue_id} not found")


def approve(source_id: str, queue_id: str, *, reviewer: str, wait: bool = False) -> dict:
    from . import publish as publish_mod

    item = _update_status(source_id, queue_id, "approved", reviewer=reviewer)
    result = publish_mod.publish_one(
        Path(item["path"]),
        assessment=item.get("assessment"),
        agent=item.get("agent", "unknown"),
        trigger="maintenance",
        wait=wait,
    )
    audit.append(
        source_id,
        {
            "event": "queue_approved",
            "queue_id": queue_id,
            "key": item["key"],
            "reviewer": reviewer,
            "author": item.get("agent"),
            "document_id": result.document_id,
        },
    )
    return item


def reject(source_id: str, queue_id: str, *, reviewer: str, reason: str) -> dict:
    item = _update_status(source_id, queue_id, "rejected", reviewer=reviewer)
    audit.append(
        source_id,
        {"event": "queue_rejected", "queue_id": queue_id, "key": item["key"], "reviewer": reviewer, "reason": reason},
    )
    return item
