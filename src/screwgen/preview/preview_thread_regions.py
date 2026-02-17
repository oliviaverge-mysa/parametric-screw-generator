"""Preview/export harness for thread-region placeholder markers (no helix)."""

from __future__ import annotations

import argparse
import cadquery as cq

from ..assembly import make_screw_from_spec
from ..export import export_step, export_stl, out_path
from ..spec import DriveSpec, HeadSpec, ScrewSpec, ShaftSpec, SmoothRegionSpec, ThreadRegionSpec

HEAD_TYPES = ["flat", "pan", "button", "hex"]
DRIVES = [
    DriveSpec(type="hex", size=3),
    DriveSpec(type="phillips", size=4),
    DriveSpec(type="torx", size=6),
]

BASE_SHAFT = ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0)
REGION_CASES: list[tuple[str, list[object]]] = [
    ("fullsmooth", [SmoothRegionSpec(length=30.0)]),
    ("partial", [ThreadRegionSpec(length=18.0, pitch=1.0), SmoothRegionSpec(length=12.0)]),
    (
        "threadgapthread",
        [
            ThreadRegionSpec(length=10.0, pitch=1.0),
            SmoothRegionSpec(length=5.0),
            ThreadRegionSpec(length=10.0, pitch=1.0),
            SmoothRegionSpec(length=5.0),
        ],
    ),
]


def _head_spec(head_type: str) -> HeadSpec:
    if head_type == "hex":
        return HeadSpec(type="hex", d=8.0, h=4.0, acrossFlats=7.0)
    return HeadSpec(type=head_type, d=8.0, h=4.0)


def _section_x_negative(solid: cq.Workplane) -> cq.Workplane:
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.25, 50.0)
    sy = max((bb.ymax - bb.ymin) * 1.25, 50.0)
    sz = max((bb.zmax - bb.zmin) * 1.25, 80.0)
    cutter = (
        cq.Workplane("XY")
        .box(sx, sy, sz, centered=(False, True, False))
        .translate((-sx, 0, bb.zmin - 0.2 * sz))
    )
    return solid.intersect(cutter)


def build_thread_region_gallery_solids() -> list[cq.Workplane]:
    solids: list[cq.Workplane] = []
    for h_idx, head_type in enumerate(HEAD_TYPES):
        for d_idx, drive in enumerate(DRIVES):
            for r_idx, (_, regions) in enumerate(REGION_CASES):
                spec = ScrewSpec(
                    head=_head_spec(head_type),
                    drive=drive,
                    shaft=BASE_SHAFT,
                    regions=list(regions),  # copy
                )
                screw = make_screw_from_spec(spec, include_thread_markers=True)
                x = h_idx * 85.0
                y = d_idx * 30.0
                z = r_idx * 40.0
                solids.append(screw.translate((x, y, z)))
    return solids


def export_thread_region_gallery(output_dir=None) -> tuple:
    solids = build_thread_region_gallery_solids()
    comp = cq.Compound.makeCompound([s.val() for s in solids])
    wp = cq.Workplane(obj=comp)
    if output_dir is None:
        gallery = export_step(wp, out_path("galleries", "step", "thread_region_gallery.step"))
        section = export_step(
            _section_x_negative(wp),
            out_path("galleries", "sectioned/step", "thread_region_gallery_section.step"),
        )
    else:
        gallery = export_step(wp, "thread_region_gallery.step", output_dir)
        section = export_step(_section_x_negative(wp), "thread_region_gallery_section.step", output_dir)
    return gallery, section, len(solids)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate thread-region marker previews.")
    parser.add_argument("--stl", action="store_true", help="Export STL files.")
    parser.add_argument("--stl-tol", type=float, default=0.25, help="STL linear tolerance.")
    parser.add_argument("--stl-ang", type=float, default=0.35, help="STL angular tolerance.")
    args = parser.parse_args()

    print("Output root: out/\n")
    for head_type in HEAD_TYPES:
        for drive in DRIVES:
            for label, regions in REGION_CASES:
                spec = ScrewSpec(
                    head=_head_spec(head_type),
                    drive=drive,
                    shaft=BASE_SHAFT,
                    regions=list(regions),
                )
                screw = make_screw_from_spec(spec, include_thread_markers=True)
                base = f"threadregion_{head_type}__{drive.type}__{label}"
                p_step = export_step(screw, out_path("screws", "step", f"{base}.step"))
                print(f"  [{base}] STEP -> {p_step}")
                if args.stl:
                    p_stl = export_stl(
                        screw,
                        out_path("screws", "stl", f"{base}.stl"),
                        tolerance=args.stl_tol,
                        angular_tolerance=args.stl_ang,
                    )
                    print(f"  [{base}] STL  -> {p_stl}")
    gallery, section, count = export_thread_region_gallery()
    print(f"\nthread_region_gallery.step -> {gallery}")
    print(f"thread_region_gallery_section.step -> {section}")
    print(f"gallery solids: {count}")
    print("\nDone.")


if __name__ == "__main__":
    main()

