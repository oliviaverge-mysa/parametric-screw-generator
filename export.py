"""
Export utilities for screw-head solids.

Provides STEP (B-Rep) and STL (mesh) export for CadQuery workplanes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

import cadquery as cq

# Default output directory (sibling to this file)
_DEFAULT_DIR = Path(__file__).resolve().parent / "outputs"


def _ensure_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


def export_step(
    solid: cq.Workplane,
    filename: str,
    directory: Union[str, Path, None] = None,
) -> Path:
    """Export *solid* as a STEP file.

    Returns the absolute path of the written file.
    """
    out_dir = Path(directory) if directory else _DEFAULT_DIR
    _ensure_dir(out_dir)
    path = out_dir / filename
    cq.exporters.export(solid, str(path), exportType="STEP")
    return path.resolve()


def export_stl(
    solid: cq.Workplane,
    filename: str,
    directory: Union[str, Path, None] = None,
    tolerance: float = 0.05,
    angular_tolerance: float = 0.2,
) -> Path:
    """Export *solid* as an STL file.

    Returns the absolute path of the written file.
    """
    out_dir = Path(directory) if directory else _DEFAULT_DIR
    _ensure_dir(out_dir)
    path = out_dir / filename
    cq.exporters.export(
        solid,
        str(path),
        exportType="STL",
        tolerance=tolerance,
        angularTolerance=angular_tolerance,
    )
    return path.resolve()


def export_head(
    solid: cq.Workplane,
    head_type: str,
    directory: Union[str, Path, None] = None,
) -> tuple[Path, Path]:
    """Export a head as both STEP and STL.

    Filenames follow the pattern ``head_<type>.step`` / ``head_<type>.stl``.
    Returns *(step_path, stl_path)*.
    """
    step = export_step(solid, f"head_{head_type}.step", directory)
    stl = export_stl(solid, f"head_{head_type}.stl", directory)
    return step, stl
