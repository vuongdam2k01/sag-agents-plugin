#!/usr/bin/env python3
"""Bootstrap to run `sagctl` as a standalone command (without needing `python -m`
from the right directory). This is the script the PATH shim points to."""
import sys
from pathlib import Path

# Force UTF-8 for stdout/stderr — the default Windows console (cp1252/cp437)
# cannot encode Vietnamese text, and all of the engine's output uses Vietnamese.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sagctl.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
