"""Secret scan mandatory before every upload (SPEC S4).

SAG has no per-reader ACL (single-user) — once a secret is in SAG, EVERY agent
can read it. REVIEW-OPUS F27: this is a deterministic floor, blocks by default;
the remediation path when something leaks through is `sag_unpublish`, not
turning off the scan.

Uses `gitleaks` from PATH if available (better detection) — falls back to a
pure stdlib regex+entropy scan if not, so as not to create a mandatory
external dependency.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Finding:
    kind: str
    line: int
    snippet: str


_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret_hint", re.compile(r"(?i)aws(?:.{0,20})?secret(?:.{0,20})?['\"][0-9a-zA-Z/+]{40}['\"]")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("jwt_like", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("generic_api_key_assign", re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{16,}['\"]")),
]

_HEX32 = re.compile(r"\b[0-9a-fA-F]{32,}\b")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _high_entropy_tokens(line: str, min_len: int = 24, min_entropy: float = 3.8) -> list[str]:
    hits = []
    for m in _HEX32.finditer(line):
        tok = m.group(0)
        if len(tok) >= min_len and _shannon_entropy(tok) >= min_entropy:
            hits.append(tok)
    return hits


def _scan_regex(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _PATTERNS:
            m = pattern.search(line)
            if m:
                findings.append(Finding(kind=kind, line=lineno, snippet=_redact(line)))
        for tok in _high_entropy_tokens(line):
            findings.append(Finding(kind="high_entropy_token", line=lineno, snippet=_redact(line)))
    return findings


def _redact(line: str, keep: int = 6) -> str:
    stripped = line.strip()
    if len(stripped) <= keep * 2:
        return "*" * len(stripped)
    return stripped[:keep] + "…redacted…" + stripped[-keep:]


def _gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


def _scan_gitleaks(text: str) -> list[Finding] | None:
    if not _gitleaks_available():
        return None
    try:
        proc = subprocess.run(
            ["gitleaks", "detect", "--no-git", "--pipe", "--report-format", "json", "--exit-code", "0"],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = proc.stdout.strip()
    if not out:
        return []
    try:
        import json

        results = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    findings = []
    for r in results:
        findings.append(
            Finding(
                kind=r.get("RuleID", "gitleaks_finding"),
                line=r.get("StartLine", 0),
                snippet=_redact(r.get("Match", "")),
            )
        )
    return findings


def scan_text(text: str) -> list[Finding]:
    """Run gitleaks if it's on PATH, always adding the stdlib regex+entropy scan
    on top (defense-in-depth — gitleaks may lack a rule for a project-internal pattern)."""
    findings: list[Finding] = []
    gl = _scan_gitleaks(text)
    if gl:
        findings.extend(gl)
    findings.extend(_scan_regex(text))
    return findings


def scan_file(path) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return scan_text(text)
