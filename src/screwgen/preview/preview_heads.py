"""Preview harness for head-only exports."""

from __future__ import annotations

import argparse
import warnings

import cadquery as cq

from ..export import export_step, export_stl, out_path
from ..heads import HeadParams, make_head

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
    parser = argparse.ArgumentParser(description="Generate head previews.")
    parser.add_argument("--stl", action="store_true", help="Export STL files.")
    args = parser.parse_args()

    print("Output root: out/\n")
    solids: list[tuple[str, cq.Workplane]] = []
    for spec in _HEAD_SPECS:
        head_type = spec["type"]
        solid = make_head(spec)
        solids.append((head_type, solid))
        step_path = export_step(solid, out_path("heads", "step", f"head_{head_type}.step"))
        print(f"  [{head_type:>6}]  STEP -> {step_path}")
        if args.stl:
            stl_path = export_stl(solid, out_path("heads", "stl", f"head_{head_type}.stl"))
            print(f"  [{head_type:>6}]  STL  -> {stl_path}")

    gallery = cq.Assembly()
    for idx, (head_type, solid) in enumerate(solids):
        gallery.add(solid, name=head_type, loc=cq.Location(cq.Vector(idx * _GALLERY_SPACING, 0, 0)))
    gallery_path = out_path("galleries", "step", "head_gallery.step")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        gallery.save(str(gallery_path), exportType="STEP")
    print(f"  Gallery STEP -> {gallery_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()

