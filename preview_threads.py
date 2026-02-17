"""Backward-compatible real-thread preview entrypoint."""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from screwgen.preview.preview_threads import main


if __name__ == "__main__":
    main()

