"""Inject provenance into the upload bytes (SPEC S3).

Injects ONLY into the bytes sent to SAG — NEVER modifies the file on disk. The
file in the repo is the identity (used for hash/dedupe — see gitutil.hash_object
on the original file), the upload bytes are the published version. If the file
already has YAML frontmatter, merge into the existing block instead of creating
a second `---` block (REVIEW-OPUS gate turn2: prepending a new block would break
the document's real frontmatter).

Deliberate limitation: this is NOT a full YAML parser (stdlib has no yaml
package). It only handles the "flat key: value" subset that this plugin's own
provenance + doc-template use. If a file has complex YAML frontmatter (nested,
multi-line lists, anchors...), the merge is still SAFE (does not break the
original structure) because it only appends lines to the end of the existing
block — but it does not re-parse the values that are already there.
"""
from __future__ import annotations

import re

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

PROVENANCE_KEYS = (
    "sag_key",
    "sag_source_commit",
    "sag_source_blob",
    "sag_published_at",
    "sag_status",
    "sag_route",
)


def _format_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    # string: quote if it contains special YAML characters so SAG's parser isn't broken
    s = str(v)
    if re.search(r'[:#\[\]{}"\']', s) or s != s.strip():
        return '"' + s.replace('"', '\\"') + '"'
    return s


# Only these carry provenance inside the uploaded bytes. Prepending a YAML block to
# a .json corrupts it, to a .py breaks it, to a .pdf is impossible — which is exactly
# why everything else used to be excluded from publishing altogether. It no longer is:
# provenance for the rest lives in the state store (SPEC A1/A3).
FRONTMATTER_FORMATS = {".md", ".markdown"}


def can_carry_frontmatter(path) -> bool:
    from pathlib import Path as _P

    return _P(path).suffix.lower() in FRONTMATTER_FORMATS


def inject(original_text: str, provenance: dict) -> str:
    prov_lines = "\n".join(f"{k}: {_format_value(v)}" for k, v in provenance.items())
    m = _FRONTMATTER_RE.match(original_text)
    if m:
        existing_yaml = m.group(1).rstrip("\n")
        new_yaml = existing_yaml + "\n" + prov_lines
        return original_text[: m.start()] + "---\n" + new_yaml + "\n---\n" + original_text[m.end() :]
    return "---\n" + prov_lines + "\n---\n\n" + original_text


def strip_for_comparison(text: str) -> str:
    """Remove the provenance keys from the frontmatter, used when comparing SAG
    content with the repo (S10 post-hoc review) — provenance changes on every
    publish, so it must be stripped before comparing whether the content actually
    changed.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return text
    lines = m.group(1).split("\n")
    kept = [ln for ln in lines if not any(ln.strip().startswith(k + ":") for k in PROVENANCE_KEYS)]
    if not kept:
        return text[m.end() :]
    new_yaml = "\n".join(kept)
    return text[: m.start()] + "---\n" + new_yaml + "\n---\n" + text[m.end() :]


def extract_frontmatter_field(text: str, field: str) -> str | None:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    for line in m.group(1).split("\n"):
        stripped = line.strip()
        if stripped.startswith(field + ":"):
            val = stripped[len(field) + 1 :].strip()
            return val.strip('"').strip("'")
    return None
