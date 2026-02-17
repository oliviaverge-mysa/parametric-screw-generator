"""Compatibility wrapper. Prefer `screwgen.assembly.make_screw`."""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from screwgen.assembly import make_screw

__all__ = ["make_screw"]

