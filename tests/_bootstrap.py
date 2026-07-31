"""Add scripts/ to sys.path so tests can import the sagctl package — run:
python -m unittest discover -s tests
"""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
