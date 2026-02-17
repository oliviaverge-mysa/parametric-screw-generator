"""Preview/export harness for real external thread v1."""

from __future__ import annotations

import argparse
import cadquery as cq

from ..assembly import make_screw_from_spec
from ..export import export_step, export_stl, out_path
from ..spec import DriveSpec, HeadSpec, ScrewSpec, ShaftSpec, SmoothRegionSpec, ThreadRegionSpec

PITCHES = [0.8, 1.0, 1.5]
SHAFT = ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0)
SPECS = [
    ("pan", DriveSpec(type="torx", size=6)),
    ("flat", DriveSpec(type="hex", size=3)),
]


def _head(head_type: str) -> HeadSpec:
    return HeadSpec(type=head_type, d=8.0, h=4.0, acrossFlats=7.0 if head_type == "hex" else None)


def _section_x_negative(solid: cq.Workplane) -> cq.Workplane:
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.2, 60.0)
    sy = max((bb.ymax - bb.ymin) * 1.2, 40.0)
    sz = max((bb.zmax - bb.zmin) * 1.2, 80.0)
    cutter = (
        cq.Workplane("XY")
        .box(sx, sy, sz, centered=(False, True, False))
        .translate((-sx, 0, bb.zmin - 0.2 * sz))
    )
    return solid.intersect(cutter)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate small real-thread previews.")
    parser.add_argument("--stl", action="store_true", help="Export STL files.")
    parser.add_argument("--stl-tol", type=float, default=0.25, help="STL linear tolerance.")
    parser.add_argument("--stl-ang", type=float, default=0.35, help="STL angular tolerance.")
    args = parser.parse_args()

    print("Output root: out/\n")
    for head_type, drive in SPECS:
        for pitch in PITCHES:
            spec = ScrewSpec(
                head=_head(head_type),
                drive=drive,
                shaft=SHAFT,
                regions=[
                    SmoothRegionSpec(length=2.0),
                    ThreadRegionSpec(length=20.0, pitch=pitch),
                    SmoothRegionSpec(length=8.0),
                ],
            )
            screw = make_screw_from_spec(spec, include_thread_markers=False)
            base = f"threaded_{head_type}__{drive.type}__p{str(pitch).replace('.', 'p')}"
            p_step = export_step(screw, out_path("screws", "step", f"{base}.step"))
            p_sec = export_step(_section_x_negative(screw), out_path("galleries", "sectioned/step", f"{base}_section.step"))
            print(f"  [{base}] STEP -> {p_step}")
            if args.stl:
                p_stl = export_stl(
                    screw,
                    out_path("screws", "stl", f"{base}.stl"),
                    tolerance=args.stl_tol,
                    angular_tolerance=args.stl_ang,
                )
                print(f"  [{base}] STL  -> {p_stl}")
            print(f"  [{base}] SECTION -> {p_sec}")
    print("\nDone.")


if __name__ == "__main__":
    main()

