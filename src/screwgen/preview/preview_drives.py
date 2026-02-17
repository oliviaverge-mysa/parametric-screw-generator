"""Preview harness for drive-only and head+drive exports."""

from __future__ import annotations

import argparse
import warnings

import cadquery as cq

from ..assembly import apply_drive_to_head
from ..drives import DriveParams, make_drive_cut
from ..export import export_step, export_stl, out_path
from ..heads import HeadParams, head_tool_z, make_head

_HEAD_SIZES: list[tuple[float, float]] = [(6.0, 3.0), (8.0, 4.0), (12.0, 6.0)]
_HEAD_TYPES = ("flat", "pan", "button", "hex")
_GALLERY_SPACING_X = 18.0
_GALLERY_SPACING_Y = 18.0


def _head_spec(head_type: str, d: float, h: float) -> HeadParams:
    if head_type == "hex":
        return {"type": "hex", "d": d, "h": h, "acrossFlats": 0.88 * d}
    return {"type": head_type, "d": d, "h": h}  # type: ignore[return-value]


def _drive_specs_for_head(head_params: HeadParams) -> list[DriveParams]:
    d = float(head_params["d"])
    h = float(head_params["h"])
    depth = min(2.0, 0.45 * h)
    tool_z = head_tool_z(head_params)
    return [
        DriveParams(type="hex", size=3, depth=depth, topZ=tool_z, fit="scale_to_head", head_d=d),
        DriveParams(type="phillips", size=4, depth=depth, topZ=tool_z, fit="scale_to_head", head_d=d),
        DriveParams(type="torx", size=6, depth=depth, topZ=tool_z, fit="scale_to_head", head_d=d),
    ]


def _section_half_x_negative(solid: cq.Workplane) -> cq.Workplane:
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.2, 20.0)
    sy = max((bb.ymax - bb.ymin) * 1.5, 20.0)
    sz = max((bb.zmax - bb.zmin) * 1.5, 20.0)
    cutter = cq.Workplane("XY").box(sx, sy, sz, centered=(False, True, False)).translate((-sx, 0, bb.zmin - 0.25 * sz))
    return solid.intersect(cutter)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate drive previews.")
    parser.add_argument("--stl", action="store_true", help="Export STL files.")
    parser.add_argument("--stl-tol", type=float, default=0.25, help="STL linear tolerance.")
    parser.add_argument("--stl-ang", type=float, default=0.35, help="STL angular tolerance.")
    args = parser.parse_args()

    print("Output root: out/\n")
    print("== Drive-only solids ==")
    ref_head = _head_spec("pan", 8.0, 4.0)
    for dp in _drive_specs_for_head(ref_head):
        cut = make_drive_cut(dp)
        label = f"{dp.type}_{dp.size}"
        sp = export_step(cut, out_path("drives", "step", f"drive_{label}.step"))
        print(f"  [{label:>12}]  STEP -> {sp}")
        if args.stl:
            tp = export_stl(
                cut,
                out_path("drives", "stl", f"drive_{label}.stl"),
                tolerance=args.stl_tol,
                angular_tolerance=args.stl_ang,
            )
            print(f"  [{label:>12}]  STL  -> {tp}")

    print("\n== Head + drive combos ==")
    combo_solids: list[tuple[str, cq.Workplane]] = []
    for d, h in _HEAD_SIZES:
        for htype in _HEAD_TYPES:
            hspec = _head_spec(htype, d, h)
            head = make_head(hspec)
            for dp in _drive_specs_for_head(hspec):
                combo = apply_drive_to_head(head, dp, hspec)
                label = f"{htype}_d{int(d)}__{dp.type}"
                combo_solids.append((label, combo))
                fname_base = f"head_{htype}_d{int(d)}_h{int(h)}__drive_{dp.type}"
                sp = export_step(combo, out_path("screws", "step", f"{fname_base}.step"))
                print(f"  [{label:>22}]  STEP -> {sp}")
                if args.stl:
                    tp = export_stl(
                        combo,
                        out_path("screws", "stl", f"{fname_base}.stl"),
                        tolerance=args.stl_tol,
                        angular_tolerance=args.stl_ang,
                    )
                    print(f"  [{label:>22}]  STL  -> {tp}")
                section = _section_half_x_negative(combo)
                section_name = f"head_{htype}__{dp.type}_section_d{int(d)}"
                sp_section = export_step(section, out_path("galleries", "sectioned/step", f"{section_name}.step"))
                print(f"  [{label:>22}]  SECTION -> {sp_section}")

    print("\nBuilding combo gallery...")
    gallery = cq.Assembly()
    columns = 12
    for idx, (label, solid) in enumerate(combo_solids):
        row = idx // columns
        col = idx % columns
        gallery.add(solid, name=label, loc=cq.Location(cq.Vector(col * _GALLERY_SPACING_X, row * _GALLERY_SPACING_Y, 0)))
    gallery_path = out_path("galleries", "step", "drive_combo_gallery.step")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        gallery.save(str(gallery_path), exportType="STEP")
    print(f"  Gallery STEP -> {gallery_path.resolve()}")
    print("\nDone.")


if __name__ == "__main__":
    main()

