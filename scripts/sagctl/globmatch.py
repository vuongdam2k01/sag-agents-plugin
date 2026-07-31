"""Glob matching with `**` following correct globstar semantics (matches ZERO or
MORE directories).

`fnmatch.fnmatch` does NOT understand path structure — it requires literal `/`
characters in the pattern to match a literal `/` at the exact same position in
the string, so `fnmatch.fnmatch("docs/x.md", "docs/**/*.md")` incorrectly
returns `False` (a file sitting directly inside `docs/`, with no subdirectory,
"should" match — this is the standard semantics of `**` in
gitignore/bash globstar/pathlib.Path.glob).

This bug directly affects whether a manifest example like
`include: ["docs/**/*.md"]` can publish a document sitting right inside
`docs/` — it must be fixed correctly before trusting any route/gate behavior
that uses include/exclude/deny/ask.
"""
from __future__ import annotations

import fnmatch


def _segments_match(path_segs: tuple[str, ...], pat_segs: tuple[str, ...]) -> bool:
    if not pat_segs:
        return not path_segs
    head = pat_segs[0]
    if head == "**":
        # ** matches ZERO directories (skip itself) ...
        if _segments_match(path_segs, pat_segs[1:]):
            return True
        # ... or matches one directory and tries again (recursion consumes the path incrementally)
        if path_segs and _segments_match(path_segs[1:], pat_segs):
            return True
        return False
    if not path_segs:
        return False
    if fnmatch.fnmatch(path_segs[0], head):
        return _segments_match(path_segs[1:], pat_segs[1:])
    return False


def match(relpath: str, pattern: str) -> bool:
    path_segs = tuple(s for s in relpath.split("/") if s)
    pat_segs = tuple(pattern.split("/"))
    return _segments_match(path_segs, pat_segs)


def match_any(relpath: str, patterns: list[str]) -> bool:
    return any(match(relpath, p) for p in patterns)
