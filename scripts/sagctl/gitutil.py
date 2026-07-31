"""Git subprocess wrapper — the foundation for S2 (hash), S4 (floor), S9 (rename), S10 (tie-break).

Every function here only reads Git state, never writes (no commit/push/checkout).
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def toplevel(start: Path) -> Path | None:
    d = start if start.is_dir() else start.parent
    result = _run(["rev-parse", "--show-toplevel"], cwd=d, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def hash_object(path: Path) -> str:
    """git hash-object on the bytes currently on disk — normalizes CRLF per the
    user's Git config, unlike a raw sha256 (REVIEW-OPUS F25: a raw sha256 turns
    every Windows<->Linux machine switch into a full corpus re-ingest).
    """
    result = _run(["hash-object", str(path)], cwd=path.parent)
    return result.stdout.strip()


def status_porcelain_for(relpath_from_root: str, repo_root: Path) -> str:
    result = _run(["status", "--porcelain", "--", relpath_from_root], cwd=repo_root)
    return result.stdout


def head_commit(repo_root: Path) -> str:
    return _run(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()


def current_branch(repo_root: Path) -> str:
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root).stdout.strip()


def commit_exists(sha: str, repo_root: Path) -> bool:
    """Distinguish 'not an ancestor' from 'unknown whether this commit exists'.

    REVIEW-OPUS C3 points out: is-ancestor returns false EVEN WHEN the commit
    is not present in the clone (shallow, not fetched) — without checking
    existence first, tie-break will pick the wrong winner and delete the
    correct version by mistake. Always call this function before is_ancestor().
    """
    result = _run(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_root, check=False)
    return result.returncode == 0


def is_ancestor(sha: str, ref: str, repo_root: Path) -> bool:
    result = _run(["merge-base", "--is-ancestor", sha, ref], cwd=repo_root, check=False)
    return result.returncode == 0


def rev_list_count(sha: str, ref: str, repo_root: Path) -> int:
    result = _run(["rev-list", "--count", f"{sha}..{ref}"], cwd=repo_root, check=False)
    if result.returncode != 0:
        return -1
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def fetch(repo_root: Path, remote: str = "origin", branch: str | None = None) -> bool:
    args = ["fetch", remote]
    if branch:
        args.append(branch)
    result = _run(args, cwd=repo_root, check=False)
    return result.returncode == 0


def path_exists_at_ref(relpath: str, ref: str, repo_root: Path) -> bool:
    result = _run(["cat-file", "-e", f"{ref}:{relpath}"], cwd=repo_root, check=False)
    return result.returncode == 0


def blob_at_ref(relpath: str, ref: str, repo_root: Path) -> str | None:
    result = _run(["rev-parse", f"{ref}:{relpath}"], cwd=repo_root, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def last_commit_touching(relpath: str, repo_root: Path) -> str | None:
    result = _run(["log", "-1", "--format=%H", "--", relpath], cwd=repo_root, check=False)
    out = result.stdout.strip()
    return out or None
