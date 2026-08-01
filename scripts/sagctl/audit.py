"""Audit log + cost/rate counters — outside the write reach of the agent in the
workspace (SPEC S1/S4). This is the evidence for post-hoc review (S10) and the
place where R3's (DESIGN.md) "attribution" actually means something, since the
agent inside the repo cannot write/modify it.

WHERE it lives is decided by `state.py` (SPEC S1 amendment A1): the local
`~/.sagctl/` files by default, or one fleet-shared state service when
`SAGCTL_STATE_URL` is set. This module holds the SEMANTICS (what an audit record
is, what the cap means); it no longer holds the storage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import state


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(source_id: str, event: dict) -> None:
    state.audit_append(source_id, {"ts": _now_iso(), **event})


def read_all(source_id: str) -> list[dict]:
    return state.audit_read(source_id)


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


def _today() -> str:
    return state.today_utc()


def check_cost_cap(source_id: str, manifest: dict, key: str) -> tuple[bool, str]:
    """Check WITHOUT recording — used in gate.py before the actual upload runs.

    With the shared backend this cap becomes what the manifest always claimed it
    was: one budget for the whole fleet, not one per host.
    """
    data = state.cost_get(source_id)
    if data.get("day") != _today():
        return True, ""
    if data.get("publishes", 0) >= manifest.get("max_publishes_per_day", 30):
        return False, f"exceeds max_publishes_per_day={manifest.get('max_publishes_per_day')}"
    per_key_count = data.get("per_key", {}).get(key, 0)
    if per_key_count >= 5:
        return False, f"key '{key}' already published {per_key_count} times today — suspected republish loop"
    return True, ""


def bump_cost_counter(source_id: str, key: str) -> None:
    state.cost_bump(source_id, key)


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
