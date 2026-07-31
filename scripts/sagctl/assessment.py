"""Contract for the self-assessment an agent generates before publishing (SPEC S5).

This is a "structured rubric" — the agent's obligation ("is this knowledge
worth putting into the knowledge base?") is forced into typed, verifiable data,
used as input to routing (S6) and to later post-hoc review (S10) re-scoring.
`canonical`/`secret_free` are NOT part of the assessment — that is the job of
the deterministic floor (gate.py), not the model's judgment (REVIEW-OPUS gate
turn2 D5: don't let the model "self-report" work that belongs to the machine).

`initiator`, `key`, `criteria_available` are filled in by the ENGINE, never
taken from the model — this is where the "model self-reports that the user
gave the order" loophole is blocked (REVIEW-OPUS §2c).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import CONTRACT_VERSION

VALID_VERDICTS = {"knowledge", "not-knowledge", "unsure"}
VALID_INITIATORS = {"agent-auto", "user-manual", "queue-approved"}
VALID_TRIGGERS = {"post-write-hook", "end-of-task", "user-command", "maintenance"}

_REQUIRED_TOP = (
    "path",
    "source_id",
    "commit",
    "verdict",
    "durable",
    "audience",
    "retrieval_fit",
    "confidence",
    "rationale",
)
_REQUIRED_SUBFIELDS = ("pass", "why")


class AssessmentError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_model_input(a: dict) -> list[str]:
    """Check the fields the agent is REQUIRED to supply — excludes the fields the engine fills in."""
    errors: list[str] = []
    for f in _REQUIRED_TOP:
        if f not in a:
            errors.append(f"missing required field: {f}")
    if "verdict" in a and a["verdict"] not in VALID_VERDICTS:
        errors.append(f"verdict must be one of {VALID_VERDICTS}, got '{a.get('verdict')}'")
    for sub in ("durable", "audience", "retrieval_fit"):
        v = a.get(sub)
        if v is not None:
            if not isinstance(v, dict) or any(k not in v for k in _REQUIRED_SUBFIELDS):
                errors.append(f"{sub} must be an object with 'pass' and 'why'")
    conf = a.get("confidence")
    if conf is not None and (not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0)):
        errors.append("confidence must be a number in [0.0, 1.0]")
    rationale = a.get("rationale")
    if rationale is not None and not str(rationale).strip():
        errors.append("rationale must not be empty")
    ack = a.get("criteria_ack", [])
    if not isinstance(ack, list) or not all(isinstance(x, str) for x in ack):
        errors.append("criteria_ack must be a list of string ids")
    return errors


def enrich(
    a: dict,
    *,
    initiator: str,
    trigger: str,
    agent: str,
    key: str,
    criteria_available: list[str],
) -> dict:
    """Engine fills in the fields the model is not allowed to self-report, returns the complete assessment."""
    if initiator not in VALID_INITIATORS:
        raise AssessmentError(f"invalid initiator: {initiator}")
    if trigger not in VALID_TRIGGERS:
        raise AssessmentError(f"invalid trigger: {trigger}")
    out = dict(a)
    out["schema_version"] = CONTRACT_VERSION
    out["assessed_at"] = a.get("assessed_at") or _now_iso()
    out["initiator"] = initiator
    out["trigger"] = trigger
    out["agent"] = agent
    out["key"] = key
    out["criteria_available"] = criteria_available
    out.setdefault("criteria_ack", [])
    return out


@dataclass
class ManualContext:
    """Not an assessment — used when route = manual (S7), bypassing the rubric."""

    initiator: str = "user-manual"
    trigger: str = "user-command"
    reason: str = ""
