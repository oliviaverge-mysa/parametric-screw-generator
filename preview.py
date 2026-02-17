"""
Preview harness for the screw-head generator.

Generates one example of each head type, exports individual STEP/STL files,
and creates a combined gallery STEP for visual inspection.

Run:
    python preview.py
"""

from __future__ import annotations

from pathlib import Path

import cadquery as cq

from head import HeadParams, make_head
from export import export_head, export_step

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"

# Example parameters — same for every head except hex gets acrossFlats.
_D = 8.0
_H = 4.0
_ACROSS_FLATS = 7.0  # hex only
_GALLERY_SPACING = 14.0  # mm between head centres along X

_HEAD_SPECS: list[HeadParams] = [
    {"type": "flat",   "d": _D, "h": _H},
    {"type": "pan",    "d": _D, "h": _H},
    {"type": "button", "d": _D, "h": _H},
    {"type": "hex",    "d": _D, "h": _H, "acrossFlats": _ACROSS_FLATS},
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Output directory: {OUTPUT_DIR}\n")

    solids: list[tuple[str, cq.Workplane]] = []

    # 1) Generate & export each head individually.
    for spec in _HEAD_SPECS:
        head_type = spec["type"]
        solid = make_head(spec)
        solids.append((head_type, solid))

        step_path, stl_path = export_head(solid, head_type, OUTPUT_DIR)
        print(f"  [{head_type:>6}]  STEP -> {step_path}")
        print(f"  [{head_type:>6}]  STL  -> {stl_path}")

    # 2) Build combined gallery — heads arranged along X axis.
    print("\nBuilding gallery...")
    gallery = cq.Assembly()

    for idx, (head_type, solid) in enumerate(solids):
        x_offset = idx * _GALLERY_SPACING
        gallery.add(
            solid,
            name=head_type,
            loc=cq.Location(cq.Vector(x_offset, 0, 0)),
        )

    gallery_path = OUTPUT_DIR / "head_gallery.step"
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        gallery.save(str(gallery_path), exportType="STEP")
    print(f"  Gallery STEP -> {gallery_path.resolve()}")

    print("\nDone.")


if __name__ == "__main__":
    main()
