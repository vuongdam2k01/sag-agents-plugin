"""Layout of ~/.sagctl/ and credentials (S1, S3, S12).

Any state an agent could overwrite (audit, cost cap, queue, credentials) must
live OUTSIDE every workspace/repo — that is a condition SPEC S1 requires, and
is the point REVIEW-OPUS F5 raises: "config inside the workspace = the agent
grants itself permissions".
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def sagctl_home() -> Path:
    home = Path(os.environ.get("SAGCTL_HOME", str(Path.home() / ".sagctl")))
    home.mkdir(parents=True, exist_ok=True)
    return home


def source_key(source_id: str) -> str:
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:12]


def source_dir(source_id: str) -> Path:
    d = sagctl_home() / source_key(source_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def audit_path(source_id: str) -> Path:
    return source_dir(source_id) / "audit.jsonl"


def queue_path(source_id: str) -> Path:
    return source_dir(source_id) / "queue.jsonl"


def cost_path(source_id: str) -> Path:
    return source_dir(source_id) / "cost.json"


def session_dir() -> Path:
    d = sagctl_home() / "session"
    d.mkdir(parents=True, exist_ok=True)
    return d


def credentials_path() -> Path:
    return sagctl_home() / "credentials.json"


FORBIDDEN_IN_REPO = ("sagctl.config.json", "queue.jsonl", "audit.jsonl", "credentials.json")


class RepoStateLeakError(RuntimeError):
    """Internal state file (audit/queue/credentials) detected inside the Git repo."""


def assert_no_repo_state_leak(repo_root: Path) -> None:
    """Refuse to run if audit/queue/credentials were placed (or self-created by an
    agent) inside the repo.

    The .sag-sync.json manifest IS allowed in the repo (it is public policy,
    reviewable via Git) — only internal state is forbidden.
    """
    for name in FORBIDDEN_IN_REPO:
        hit = list(repo_root.rglob(name))
        if hit:
            raise RepoStateLeakError(
                f"found '{name}' inside the repo at {hit[0]} — sagctl's internal "
                f"state must live outside the workspace (~/.sagctl/). Delete this file from the repo."
            )


class Credentials:
    """Read/write ~/.sagctl/credentials.json — the ONLY place the write token is kept.

    The read token belongs to the agent (env SAG_READ_TOKEN / the agent tool's
    manifest) and does NOT pass through this module — S12 keeps the two tokens
    fully separate so that a leaked read token does not also expose write access.
    """

    def __init__(self, profile: str = "default"):
        self.profile = profile
        self._path = credentials_path()

    def _load_all(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _save_all(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # best-effort on Windows — a real ACL needs icacls; leave that to a hardened install

    def get(self) -> dict | None:
        return self._load_all().get(self.profile)

    def set(self, *, url: str, write_token: str) -> None:
        data = self._load_all()
        data[self.profile] = {"url": url.rstrip("/"), "write_token": write_token}
        self._save_all(data)

    def require(self) -> dict:
        cred = self.get()
        if not cred:
            raise RuntimeError(
                f"no credentials yet for profile '{self.profile}'. Run: sagctl login"
            )
        return cred
