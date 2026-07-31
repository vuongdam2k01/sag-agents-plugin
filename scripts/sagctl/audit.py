"""Audit log + cost/rate counters — lives at ~/.sagctl/, outside the write reach
of the agent in the workspace (SPEC S1/S4). This is the evidence for post-hoc
review (S10) and the place where R3's (DESIGN.md) "attribution" actually means
something, since the agent inside the repo cannot write/modify it.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(source_id: str, event: dict) -> None:
    record = {"ts": _now_iso(), **event}
    path = config.audit_path(source_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_all(source_id: str) -> list[dict]:
    path = config.audit_path(source_id)
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


def read_since(source_id: str, days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for rec in read_all(source_id):
        try:
            ts = datetime.fromisoformat(rec["ts"])
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            out.append(rec)
    return out


# -- cost / rate cap --------------------------------------------------------


def _load_cost(source_id: str) -> dict:
    path = config.cost_path(source_id)
    if not path.exists():
        return {"day": _today(), "publishes": 0, "per_key": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"day": _today(), "publishes": 0, "per_key": {}}


def _save_cost(source_id: str, data: dict) -> None:
    config.cost_path(source_id).write_text(json.dumps(data), encoding="utf-8")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_cost_cap(source_id: str, manifest: dict, key: str) -> tuple[bool, str]:
    """Check WITHOUT recording — used in gate.py before the actual upload runs."""
    data = _load_cost(source_id)
    if data["day"] != _today():
        return True, ""
    if data["publishes"] >= manifest.get("max_publishes_per_day", 30):
        return False, f"exceeds max_publishes_per_day={manifest.get('max_publishes_per_day')}"
    per_key_count = data.get("per_key", {}).get(key, 0)
    if per_key_count >= 5:
        return False, f"key '{key}' already published {per_key_count} times today — suspected republish loop"
    return True, ""


def bump_cost_counter(source_id: str, key: str) -> None:
    data = _load_cost(source_id)
    if data["day"] != _today():
        data = {"day": _today(), "publishes": 0, "per_key": {}}
    data["publishes"] += 1
    data.setdefault("per_key", {})
    data["per_key"][key] = data["per_key"].get(key, 0) + 1
    _save_cost(source_id, data)


def fail_rate_by_agent_route(source_id: str, *, days: int = 30) -> dict:
    """Statistics for `sagctl doctor` — post-hoc review fail rate by agent x route,
    used to decide whether to lower min_confidence or revoke an agent's self
    privilege (SPEC S10 — post-hoc review is a safety net, the action belongs
    to a human in phase 1).
    """
    records = read_since(source_id, days)
    stats: dict[str, dict[str, dict[str, int]]] = {}
    for rec in records:
        if rec.get("event") != "post_review":
            continue
        agent = rec.get("agent", "unknown")
        route = rec.get("route", "unknown")
        stats.setdefault(agent, {}).setdefault(route, {"total": 0, "fail": 0})
        stats[agent][route]["total"] += 1
        if rec.get("verdict") == "fail":
            stats[agent][route]["fail"] += 1
    return stats
