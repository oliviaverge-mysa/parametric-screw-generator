"""Compatibility wrapper. Prefer `screwgen.spec`."""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from screwgen.spec import *  # noqa: F401,F403

