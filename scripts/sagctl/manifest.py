"""Manifest .sag-sync.json — unified schema (SPEC S1).

The manifest LIVES IN THE REPO (unlike audit/queue/credentials — see
config.py) because it is public policy, reviewable via Git. Publishing
requires finding a manifest that is an ancestor of the file being published —
with no manifest, nothing can be published, not even manually (SPEC S1,
REVIEW-OPUS F28/C2-L3).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import gitutil

MANIFEST_FILENAME = ".sag-sync.json"

# Resolution order when there is no file to walk up from — an agent whose working
# area is not a repo (a Hermes profile, a research session) still has a scope.
ENV_MANIFEST = "SAGCTL_MANIFEST"

DEFAULTS = {
    "sandbox_source_id": None,
    # "path" | "flat" — LOCKED IN by selftest S1 on sag.home (2026-07-31): SAG
    # truncates a multipart filename down to its basename (sends
    # "docs/adr/probe.md" -> gets back "probe.md"), so "path" is NOT usable.
    # The "flat" default is a real observed result, not an assumption — see
    # docs/SPEC.md §S2, "Selftest results" section.
    "key_format": "flat",
    # "committed" | "pushed" | "merged" — applied ONLY when the document lives inside
    # a Git repo. Outside a repo the git clause does not apply; it is not an error and
    # not a special mode. Git adds traceability where it exists; it is not the
    # precondition for a document being knowledge (SPEC A3).
    "require": "committed",
    "canonical_branch": "main",
    "min_confidence": 0.8,
    "criteria": [],  # [{"id": "...", "text": "..."}] — natural language for the agent's assessment
    "deny_paths": [],  # deterministic rule — engine blocks, including manual
    "ask_paths": [],  # deterministic rule — always goes to queue, manual can satisfy it
    # Every extension SAG accepts, not just the ones whose bytes can carry YAML
    # frontmatter. Provenance for the rest lives in the state store (SPEC A3) — the
    # old `.md`-only default was a consequence of that welding, never a judgement
    # that only markdown can be knowledge.
    "include": ["**/*"],
    "exclude": [],
    "max_files": 50,
    "max_publishes_per_day": 30,
    "stale_branch_days": 14,
}

VALID_KEY_FORMATS = {"path", "flat"}
VALID_REQUIRE = {"committed", "pushed", "merged"}


class ManifestError(RuntimeError):
    pass


def find_manifest(start: Path) -> Path | None:
    """Find the .sag-sync.json that is an ancestor of `start`, without crossing
    outside the Git repo.

    Never use a manifest from a different repo even if it is "closer" on the
    filesystem — safer on machines with multiple nested repos (submodules, monorepo children).
    """
    cur = start.resolve()
    cur = cur if cur.is_dir() else cur.parent
    repo_root = gitutil.toplevel(cur)
    while True:
        candidate = cur / MANIFEST_FILENAME
        if candidate.is_file():
            return candidate
        if repo_root is not None and cur == repo_root:
            return None
        if cur.parent == cur:
            return None
        cur = cur.parent


def validate(m: dict) -> None:
    if not m.get("source_id"):
        raise ManifestError("manifest is missing 'source_id' (required)")
    if m["key_format"] not in VALID_KEY_FORMATS:
        raise ManifestError(f"key_format must be one of {VALID_KEY_FORMATS}, got '{m['key_format']}'")
    if m["require"] not in VALID_REQUIRE:
        raise ManifestError(f"require must be one of {VALID_REQUIRE}, got '{m['require']}'")
    if m["require"] in ("pushed", "merged") and not m.get("canonical_branch"):
        # canonical_branch is ONLY consulted by pushed/merged and by maintain's
        # stale-branch check. Requiring it unconditionally made it look load-bearing
        # when it is inert under `require: committed|none`.
        raise ManifestError(f"require='{m['require']}' needs 'canonical_branch'")
    if not isinstance(m["min_confidence"], (int, float)) or not (0 <= m["min_confidence"] <= 1):
        raise ManifestError("min_confidence must be a number in [0, 1]")
    ids = [c.get("id") for c in m["criteria"]]
    if any(not cid for cid in ids):
        raise ManifestError("every criteria element must have an 'id'")
    if len(ids) != len(set(ids)):
        raise ManifestError("criteria has duplicate ids")
    for c in m["criteria"]:
        if "text" not in c or not c["text"].strip():
            raise ManifestError(f"criteria id={c.get('id')} is missing 'text'")
    for field in ("deny_paths", "ask_paths", "include", "exclude"):
        if not isinstance(m[field], list):
            raise ManifestError(f"{field} must be a list of glob patterns")
    if not isinstance(m["max_files"], int) or m["max_files"] < 1:
        raise ManifestError("max_files must be a positive integer")
    if not isinstance(m["stale_branch_days"], int) or m["stale_branch_days"] < 1:
        raise ManifestError("stale_branch_days must be a positive integer")


def load(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest {path} is not valid JSON: {e}") from e
    merged = {**DEFAULTS, **raw}
    validate(merged)
    merged["_path"] = str(path)
    merged["_repo_root"] = str(path.parent)
    return merged


def named_manifest(name: str) -> Path:
    """`~/.sagctl/manifests/<name>.json` — a scope declared outside any working tree."""
    from . import config

    return config.sagctl_home() / "manifests" / f"{name}.json"


def resolve(start: Path | None = None, *, explicit: Path | None = None, name: str | None = None) -> dict:
    """Find the manifest. A repo is one place it can live, not the only one.

    Order: explicit path -> named manifest -> $SAGCTL_MANIFEST -> walk up from `start`.
    Publishing still REQUIRES a manifest (S1) — what changed is that the manifest no
    longer has to sit above a file inside a Git checkout.
    """
    if explicit is not None:
        return load(Path(explicit))
    if name:
        path = named_manifest(name)
        if not path.is_file():
            raise ManifestError(f"no manifest named '{name}' at {path}")
        return load(path)

    import os

    env = os.environ.get(ENV_MANIFEST)
    if env:
        return load(Path(env))

    if start is not None:
        manifest_path = find_manifest(start)
        if manifest_path is not None:
            return load(manifest_path)

    raise ManifestError(
        f"no manifest found. Provide one of: --manifest <path>, a named manifest under "
        f"{named_manifest('<name>').parent}, ${ENV_MANIFEST}, or a {MANIFEST_FILENAME} "
        f"above the file being published."
    )


def load_for(start: Path) -> dict:
    return resolve(start)


def repo_root(m: dict) -> Path:
    """The manifest's directory. Called `repo_root` for history; it is only a Git repo
    when one happens to be there — see `git_root()`."""
    return Path(m["_repo_root"])


def git_root(m: dict) -> Path | None:
    """The Git toplevel containing the manifest, or None when there is no repo.

    None is a normal state, not a failure: it means the git clause of the floor does
    not apply and provenance goes to the state store instead of the upload bytes.
    """
    from . import gitutil

    return gitutil.toplevel(repo_root(m))


def relpath_of(file_path: Path, m: dict) -> str:
    file_path = file_path.resolve()
    root = repo_root(m).resolve()
    try:
        rel = file_path.relative_to(root)
    except ValueError as e:
        raise ManifestError(
            f"{file_path} is not inside the repo {root} of manifest {m['_path']}"
        ) from e
    return rel.as_posix()


def add_criterion(manifest_path: Path, criterion_id: str, text: str) -> dict:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    m.setdefault("criteria", [])
    if any(c["id"] == criterion_id for c in m["criteria"]):
        raise ManifestError(f"criteria id '{criterion_id}' already exists")
    m["criteria"].append({"id": criterion_id, "text": text})
    manifest_path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return m
