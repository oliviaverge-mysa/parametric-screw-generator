"""Export helpers for STEP/STL."""

from __future__ import annotations

from pathlib import Path
from typing import Union

import cadquery as cq

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "outputs"


def _ensure_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


def export_step(solid: cq.Workplane, filename: str, directory: Union[str, Path, None] = None) -> Path:
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


def export_head(solid: cq.Workplane, head_type: str, directory: Union[str, Path, None] = None) -> tuple[Path, Path]:
    return (
        export_step(solid, f"head_{head_type}.step", directory),
        export_stl(solid, f"head_{head_type}.stl", directory),
    )

