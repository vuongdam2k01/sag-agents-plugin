#!/usr/bin/env python3
"""Hook UserPromptSubmit — mints a manual token EXACTLY ONCE, ONLY when the
prompt matches the exact `/sag-publish <args>` form (SPEC S7). This is the
only place a token gets created — it does not mint unconditionally on every
turn (REVIEW-OPUS gate turn2 (i): unconditional minting = gates nothing).
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import output_additional_context, read_hook_input, record_session_start_commit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sagctl import gitutil, manual  # noqa: E402

_PATTERN = re.compile(r"^\s*/sag-publish\s+(.+?)\s*$")


def main() -> int:
    data = read_hook_input()
    prompt = data.get("prompt", "")
    session_id = data.get("session_id", "unknown-session")
    cwd = Path(data.get("cwd", "."))

    # Take the opportunity to record the session-start marker for the
    # Stop/SessionEnd backstop to read back — called here because
    # UserPromptSubmit is usually the earliest hook in the session.
    repo_root = gitutil.toplevel(cwd)
    if repo_root:
        record_session_start_commit(session_id, repo_root)

    m = _PATTERN.match(prompt)
    if not m:
        return 0

    args_str = m.group(1)
    token = secrets.token_urlsafe(24)
    manual.mint(args_str, token)
    output_additional_context(
        f"[sagctl manual-publish] token={token} args={args_str} — "
        f'use: sagctl publish "{args_str}" --manual-token {token}',
        "UserPromptSubmit",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
