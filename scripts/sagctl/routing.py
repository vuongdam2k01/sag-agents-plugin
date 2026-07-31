"""Publish routing — verdict first, confidence second (SPEC S6).

precedence: deny_paths > ask_paths > include/exclude > criteria > confidence
"""
from __future__ import annotations

from dataclasses import dataclass

from . import globmatch


class Route:
    AUTO = "auto"
    QUEUE = "queue"
    REJECT_NOT_KNOWLEDGE = "reject_not_knowledge"
    REJECT_DENY = "reject_deny"
    REJECT_NOT_INCLUDED = "reject_not_included"
    MANUAL = "manual"


@dataclass
class RouteDecision:
    route: str
    reason: str


def path_matches_any(relpath: str, patterns: list[str]) -> bool:
    return globmatch.match_any(relpath, patterns)


def _included(relpath: str, manifest: dict) -> bool:
    include = manifest.get("include") or ["**/*"]
    excluded = path_matches_any(relpath, manifest.get("exclude") or [])
    if excluded:
        return False
    return path_matches_any(relpath, include)


def decide(
    *,
    relpath: str,
    manifest: dict,
    assessment: dict | None,
    manual_token_valid: bool,
) -> RouteDecision:
    """`relpath` is the original POSIX relpath in the repo (not key-encoded) —
    the manifest's glob always matches on the real relpath, independent of key_format.
    """
    if path_matches_any(relpath, manifest.get("deny_paths") or []):
        return RouteDecision(Route.REJECT_DENY, "deny_paths matched — blocks manual too")

    if manual_token_valid:
        # manual still must fall within the manifest's include/exclude — it is not
        # a bypass of the whole policy, only a bypass of the assessment step.
        if not _included(relpath, manifest):
            return RouteDecision(Route.REJECT_NOT_INCLUDED, "path outside the manifest's include/exclude")
        return RouteDecision(Route.MANUAL, "manual token valid")

    if not _included(relpath, manifest):
        return RouteDecision(Route.REJECT_NOT_INCLUDED, "path outside the manifest's include/exclude")

    if assessment is None:
        return RouteDecision(Route.QUEUE, "no assessment and no manual token")

    verdict = assessment.get("verdict")
    if verdict == "not-knowledge":
        return RouteDecision(Route.REJECT_NOT_KNOWLEDGE, "verdict=not-knowledge")

    if path_matches_any(relpath, manifest.get("ask_paths") or []):
        return RouteDecision(Route.QUEUE, "ask_paths matched")

    criteria_available = manifest.get("criteria") or []
    ack = assessment.get("criteria_ack") or []
    if criteria_available and not ack:
        return RouteDecision(
            Route.QUEUE,
            "manifest has criteria but criteria_ack is empty — unclear whether the agent read "
            "the criteria, not auto (REVIEW-OPUS: 'criteria_ack has teeth')",
        )

    confidence = assessment.get("confidence", 0.0)
    min_confidence = manifest.get("min_confidence", 0.8)
    if verdict == "knowledge" and confidence >= min_confidence:
        return RouteDecision(Route.AUTO, f"verdict=knowledge, confidence={confidence}>=threshold={min_confidence}")

    return RouteDecision(Route.QUEUE, f"verdict={verdict}, confidence={confidence} below threshold")
