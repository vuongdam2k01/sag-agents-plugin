"""`sagctl eval` — simple recall@k via SAG's MCP search/grep, used to detect
retrieval-quality regressions after changing SAG's version or chunking
strategy (REVIEW-OPUS C5: eval scoped down to a harness + 5 sample questions
in phase 1; a real golden set is a per-project onboarding task — see
examples/eval/).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .restclient import SagClient


@dataclass
class EvalCase:
    question: str
    expected_key: str
    strategy: str = "vector"


@dataclass
class EvalResult:
    question: str
    expected_key: str
    hit: bool
    rank: int | None
    top_keys: list[str] = field(default_factory=list)


def load_cases(path: Path) -> list[EvalCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        cases.append(EvalCase(question=d["question"], expected_key=d["expected_key"], strategy=d.get("strategy", "vector")))
    return cases


def run(client: SagClient, source_id: str, cases: list[EvalCase], *, top_k: int = 5) -> list[EvalResult]:
    results = []
    for case in cases:
        resp = client.search(case.question, source_id=source_id, strategy=case.strategy, top_k=top_k)
        hits = resp.get("results") or resp.get("chunks") or []
        top_keys = [h.get("filename") or h.get("document_filename") or "" for h in hits]
        rank = None
        for i, k in enumerate(top_keys):
            if k == case.expected_key:
                rank = i + 1
                break
        results.append(EvalResult(question=case.question, expected_key=case.expected_key, hit=rank is not None, rank=rank, top_keys=top_keys))
    return results


def summarize(results: list[EvalResult]) -> dict:
    total = len(results)
    hits = sum(1 for r in results if r.hit)
    return {
        "total": total,
        "hits": hits,
        "recall_at_k": (hits / total) if total else 0.0,
        "misses": [r.question for r in results if not r.hit],
    }


def save_baseline(source_id: str, summary: dict, *, sag_version: str | None, key_format: str) -> Path:
    baseline_dir = config.source_dir(source_id) / "eval_baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = baseline_dir / f"{ts}.json"
    record = {
        "timestamp": ts,
        "sag_version": sag_version,
        "key_format": key_format,
        "summary": summary,
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
