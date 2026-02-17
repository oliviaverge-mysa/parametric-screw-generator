"""Preview harness for head-only exports."""

from __future__ import annotations

import warnings
from pathlib import Path

import cadquery as cq

from ..export import export_head
from ..heads import HeadParams, make_head

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "outputs"
_D = 8.0
_H = 4.0
_ACROSS_FLATS = 7.0
_GALLERY_SPACING = 14.0
_HEAD_SPECS: list[HeadParams] = [
    {"type": "flat", "d": _D, "h": _H},
    {"type": "pan", "d": _D, "h": _H},
    {"type": "button", "d": _D, "h": _H},
    {"type": "hex", "d": _D, "h": _H, "acrossFlats": _ACROSS_FLATS},
]


def main() -> None:
    print(f"Output directory: {OUTPUT_DIR}\n")
    solids: list[tuple[str, cq.Workplane]] = []
    for spec in _HEAD_SPECS:
        head_type = spec["type"]
        solid = make_head(spec)
        solids.append((head_type, solid))
        step_path, stl_path = export_head(solid, head_type, OUTPUT_DIR)
        print(f"  [{head_type:>6}]  STEP -> {step_path}")
        print(f"  [{head_type:>6}]  STL  -> {stl_path}")

    gallery = cq.Assembly()
    for idx, (head_type, solid) in enumerate(solids):
        gallery.add(solid, name=head_type, loc=cq.Location(cq.Vector(idx * _GALLERY_SPACING, 0, 0)))
    gallery_path = OUTPUT_DIR / "head_gallery.step"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        gallery.save(str(gallery_path), exportType="STEP")
    print(f"  Gallery STEP -> {gallery_path.resolve()}")
    print("\nDone.")


if __name__ == "__main__":
    main()

