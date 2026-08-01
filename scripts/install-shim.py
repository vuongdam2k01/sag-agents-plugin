#!/usr/bin/env python3
"""Create the `sagctl` shim so it can be invoked as a command, and initialize ~/.sagctl/.

Does NOT automatically modify the system/user PATH (that is an account
configuration change — the user must do it and confirm it themselves). This
script only creates the shim file and PRINTS instructions for adding it to PATH.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

# The default Windows console (cp1252/cp437) cannot encode Vietnamese text —
# force UTF-8 right from the start so every print() doesn't crash when running
# in a terminal that hasn't been configured for UTF-8 (this is a real bug
# hit during manual testing on Windows).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "scripts" / "sagctl_entry.py"

# Claude Code unpacks a plugin into a VERSIONED cache directory, e.g.
#   ~/.claude/plugins/cache/<marketplace>/<plugin>/0.1.0/
# A shim baked against that path keeps running 0.1.0 after an upgrade, silently.
# The marketplace checkout beside it
#   ~/.claude/plugins/marketplaces/<marketplace>/
# holds the same files at a stable path and is updated in place — that is the one
# to install from. Observed on a real install (Ubuntu, 2026-08-01), not inferred.
_VERSIONED_HINT = ("plugins", "cache")


def _versioned_install_warning(root: Path) -> str | None:
    parts = [p.lower() for p in root.parts]
    if not all(h in parts for h in _VERSIONED_HINT):
        return None
    stable = None
    for i, part in enumerate(root.parts):
        if part.lower() == "cache":
            stable = Path(*root.parts[:i]) / "marketplaces"
            break
    hint = f"\n  Look under: {stable}" if stable else ""
    return (
        "WARNING: installing the shim from a version-pinned plugin cache:\n"
        f"  {root}\n"
        "  After `claude plugin update` this path still points at the OLD version, so\n"
        "  `sagctl` would keep running a stale engine without saying anything.\n"
        "  Re-run this script from the marketplace checkout instead, which is updated\n"
        f"  in place at a stable path.{hint}"
    )


def main() -> int:
    sagctl_home = Path(os.environ.get("SAGCTL_HOME", str(Path.home() / ".sagctl")))
    bin_dir = sagctl_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    python_exe = sys.executable

    if os.name == "nt":
        shim_path = bin_dir / "sagctl.bat"
        shim_path.write_text(f'@echo off\r\n"{python_exe}" "{ENTRY}" %*\r\n', encoding="utf-8")
    else:
        shim_path = bin_dir / "sagctl"
        shim_path.write_text(f'#!/bin/sh\nexec "{python_exe}" "{ENTRY}" "$@"\n', encoding="utf-8")
        st = os.stat(shim_path)
        os.chmod(shim_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Created shim at: {shim_path}")
    print(f"Engine:          {ENTRY}")
    print(f"Interpreter:     {python_exe}")
    print(f"~/.sagctl/ at:   {sagctl_home}")
    print()

    warning = _versioned_install_warning(REPO_ROOT)
    if warning:
        print(warning, file=sys.stderr)
        print(file=sys.stderr)

    if os.name == "nt":
        print("Add to PATH (PowerShell, current session):")
        print(f'  $env:PATH = "{bin_dir};" + $env:PATH')
        print("To make it permanent (run yourself, this script does NOT modify PATH automatically):")
        print(f'  setx PATH "{bin_dir};%PATH%"   # then open a new terminal')
    else:
        print("Add to PATH (bash/zsh):")
        print(f'  export PATH="{bin_dir}:$PATH"')
        print(f'  # add the line above to ~/.bashrc or ~/.zshrc to make it permanent')
    print()
    print("Once 'sagctl' is on PATH, run: sagctl login --url <SAG_URL> --name <name>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
