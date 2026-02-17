"""Compatibility wrapper. Prefer `screwgen.assembly.apply_drive_to_head`."""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from screwgen.assembly import apply_drive_to_head

__all__ = ["apply_drive_to_head"]

