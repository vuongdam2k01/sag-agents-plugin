"""Proposal queue — lives at ~/.sagctl/, NOT in the repo (SPEC S1, REVIEW-OPUS
§2c: '.sag/queue.jsonl in the repo = agent approving its own queue').

approve/reject is the `queue-review` op — per SPEC S8 it must be explicitly
enabled, granted only to reviewer/orchestrator, and is not part of default ops.
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

from . import audit, state


class QueueError(RuntimeError):
    pass


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
    state.queue_add(source_id, item)
    audit.append(source_id, {"event": "queued", "queue_id": item["id"], "key": key, "reason": reason, "agent": agent})
    return item


def list_pending(source_id: str) -> list[dict]:
    return [i for i in state.queue_list(source_id) if i["status"] == "pending"]


def find(source_id: str, queue_id: str) -> dict | None:
    for item in state.queue_list(source_id):
        if item["id"] == queue_id:
            return item
    return None


def _update_status(source_id: str, queue_id: str, status: str, *, reviewer: str) -> dict:
    """Compare-and-set on `pending`.

    The check and the write happen inside the backend, not here — with a fleet
    sharing one queue, "read it, see pending, write approved" from two hosts
    would double-approve the same item.
    """
    try:
        return state.queue_set_status(source_id, queue_id, status, reviewer)
    except state.StateError as e:
        raise QueueError(str(e)) from None


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
