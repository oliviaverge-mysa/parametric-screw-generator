"""Export helpers for STEP/STL."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Union

import cadquery as cq

_OUT_ROOT = Path(__file__).resolve().parents[2] / "out"
_Category = Literal["heads", "drives", "shafts", "screws", "galleries"]
_Kind = Literal["step", "stl", "sectioned/step"]
DEFAULT_STL_TOLERANCE = 0.25
DEFAULT_STL_ANGULAR_TOLERANCE = 0.35


def ensure_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


def out_path(category: _Category, kind: _Kind, filename: str) -> Path:
    path = _OUT_ROOT / category / Path(kind) / filename
    ensure_dir(path.parent)
    return path.resolve()


def export_step(
    solid: cq.Workplane, filename_or_path: Union[str, Path], directory: Union[str, Path, None] = None
) -> Path:
    if directory is None:
        path = Path(filename_or_path)
    else:
        path = Path(directory) / str(filename_or_path)
    ensure_dir(path.parent)
    cq.exporters.export(solid, str(path), exportType="STEP")
    return path.resolve()


def export_stl(
    solid: cq.Workplane,
    filename_or_path: Union[str, Path],
    directory: Union[str, Path, None] = None,
    tolerance: float = DEFAULT_STL_TOLERANCE,
    angular_tolerance: float = DEFAULT_STL_ANGULAR_TOLERANCE,
) -> Path:
    if directory is None:
        path = Path(filename_or_path)
    else:
        path = Path(directory) / str(filename_or_path)
    ensure_dir(path.parent)
    cq.exporters.export(
        solid,
        str(path),
        exportType="STL",
        tolerance=tolerance,
        angularTolerance=angular_tolerance,
    )
    return path.resolve()


def export_head(solid: cq.Workplane, head_type: str, directory: Union[str, Path, None] = None) -> tuple[Path, Path]:
    if directory is None:
        step_path = out_path("heads", "step", f"head_{head_type}.step")
        stl_path = out_path("heads", "stl", f"head_{head_type}.stl")
        return export_step(solid, step_path), export_stl(solid, stl_path)
    return (
        export_step(solid, f"head_{head_type}.step", directory),
        export_stl(solid, f"head_{head_type}.stl", directory),
    )

