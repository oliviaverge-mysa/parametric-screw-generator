"""Threaded screws across all head/drive combos with gallery export."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cadquery as cq

from ..assembly import apply_drive_to_head
from ..cache import cached_make_head, cached_make_threaded_shaft
from ..export import export_step, export_stl, out_path
from ..heads import HeadParams, head_tool_z
from ..drives import DriveParams
from ..spec import ShaftSpec
from ..threads import ThreadParams

HEAD_TYPES = ["flat", "pan", "button", "hex"]
DRIVE_TYPES = [("hex", 3), ("phillips", 4), ("torx", 6)]
PITCHES = [0.8, 1.0, 1.5]

BASE_HEAD_D = 8.0
BASE_HEAD_H = 4.0
BASE_HEX_AF = 7.0
BASE_SHAFT = ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0)
THREAD_START = 2.0
THREAD_LENGTH = 20.0


def _head_params(head_type: str) -> HeadParams:
    if head_type == "hex":
        return {"type": "hex", "d": BASE_HEAD_D, "h": BASE_HEAD_H, "acrossFlats": BASE_HEX_AF}
    return {"type": head_type, "d": BASE_HEAD_D, "h": BASE_HEAD_H}  # type: ignore[return-value]


def _drive_params(head_params: HeadParams, drive_type: str, size: int) -> DriveParams:
    return DriveParams(
        type=drive_type,  # type: ignore[arg-type]
        size=size,  # type: ignore[arg-type]
        depth=min(2.0, 0.45 * float(head_params["h"])),
        topZ=head_tool_z(head_params),
        fit="scale_to_head",
        head_d=float(head_params["d"]),
    )


def _threaded_shaft(pitch: float) -> cq.Workplane:
    return cached_make_threaded_shaft(
        BASE_SHAFT,
        ThreadParams(
            pitch=pitch,
            length=THREAD_LENGTH,
            start_from_head=THREAD_START,
            included_angle_deg=60.0,
            mode="cut",
        ),
    )


def _compose_screw(head_type: str, drive_type: str, drive_size: int, pitch: float) -> cq.Workplane:
    from ..shaft import attach_shaft_to_head

    hp = _head_params(head_type)
    head = cached_make_head(hp)
    driven = apply_drive_to_head(head, _drive_params(hp, drive_type, drive_size), hp)
    return attach_shaft_to_head(driven, hp, _threaded_shaft(pitch))


def _section_x_negative(solid: cq.Workplane) -> cq.Workplane:
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.25, 120.0)
    sy = max((bb.ymax - bb.ymin) * 1.25, 120.0)
    sz = max((bb.zmax - bb.zmin) * 1.25, 120.0)
    cutter = (
        cq.Workplane("XY")
        .box(sx, sy, sz, centered=(False, True, False))
        .translate((-sx, 0, bb.zmin - 0.2 * sz))
    )
    return solid.intersect(cutter)


def build_thread_gallery_solids() -> list[cq.Workplane]:
    solids: list[cq.Workplane] = []
    for h_idx, head_type in enumerate(HEAD_TYPES):
        for d_idx, (drive_type, drive_size) in enumerate(DRIVE_TYPES):
            for p_idx, pitch in enumerate(PITCHES):
                screw = _compose_screw(head_type, drive_type, drive_size, pitch)
                x = h_idx * 95.0
                y = d_idx * 45.0
                z = p_idx * 48.0
                solids.append(screw.translate((x, y, z)))
    return solids


def build_thread_gallery_compound() -> cq.Workplane:
    solids = build_thread_gallery_solids()
    return cq.Workplane(obj=cq.Compound.makeCompound([s.val() for s in solids]))


def export_thread_gallery(output_dir: Path | None = None) -> tuple[Path, Path, int]:
    solids = build_thread_gallery_solids()
    wp = cq.Workplane(obj=cq.Compound.makeCompound([s.val() for s in solids]))
    if output_dir is None:
        gallery_path = export_step(wp, out_path("galleries", "step", "thread_gallery.step"))
        section_path = export_step(
            _section_x_negative(wp),
            out_path("galleries", "sectioned/step", "thread_gallery_section.step"),
        )
    else:
        gallery_path = export_step(wp, "thread_gallery.step", output_dir)
        section_path = export_step(_section_x_negative(wp), "thread_gallery_section.step", output_dir)
    return gallery_path, section_path, len(solids)


def export_individual_threaded_screws(
    include_stl: bool = False, stl_tol: float = 0.25, stl_ang: float = 0.35
) -> int:
    count = 0
    for head_type in HEAD_TYPES:
        for drive_type, drive_size in DRIVE_TYPES:
            for pitch in PITCHES:
                screw = _compose_screw(head_type, drive_type, drive_size, pitch)
                pitch_str = f"{pitch:.1f}"
                base = (
                    f"screw_{head_type}__{drive_type}{drive_size}"
                    f"__pitch{pitch_str}_dminor{int(BASE_SHAFT.d_minor)}_L{int(BASE_SHAFT.L)}"
                )
                export_step(screw, out_path("screws", "step", f"{base}.step"))
                if include_stl:
                    export_stl(
                        screw,
                        out_path("screws", "stl", f"{base}.stl"),
                        tolerance=stl_tol,
                        angular_tolerance=stl_ang,
                    )
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate threaded screw gallery.")
    parser.add_argument("--individual", action="store_true", help="Export individual screws (default: off).")
    parser.add_argument("--stl", action="store_true", help="Export STL for individual screws.")
    parser.add_argument("--stl-tol", type=float, default=0.25, help="STL linear tolerance (default: 0.25).")
    parser.add_argument("--stl-ang", type=float, default=0.35, help="STL angular tolerance (default: 0.35).")
    parser.add_argument("--thread-res", type=int, default=0, help="Reserved for future segmented thread mode.")
    parser.add_argument(
        "--skip-individual",
        action="store_true",
        help="Skip individual screw exports and generate gallery only.",
    )
    args = parser.parse_args()

    print("Output root: out/\n")
    if args.thread_res:
        print(f"Note: --thread-res={args.thread_res} reserved; current twist-extrude thread path ignores it.")

    t0 = time.perf_counter()
    if args.individual and not args.skip_individual:
        count = export_individual_threaded_screws(
            include_stl=args.stl,
            stl_tol=args.stl_tol,
            stl_ang=args.stl_ang,
        )
        print(f"Individual threaded screws exported: {count}")
    t1 = time.perf_counter()
    gallery, section, gcount = export_thread_gallery()
    t2 = time.perf_counter()
    print(f"thread_gallery.step -> {gallery}")
    print(f"thread_gallery_section.step -> {section}")
    print(f"gallery solids: {gcount}")
    print(f"timing: individual={t1 - t0:.2f}s gallery+section={t2 - t1:.2f}s")
    print("\nDone.")


if __name__ == "__main__":
    main()

