"""Preview harness for shaft-only and head+shaft solids."""

from __future__ import annotations

import argparse
from pathlib import Path

import cadquery as cq

from ..export import export_step, export_stl, out_path
from ..heads import HeadParams, make_head
from ..shaft import ShaftParams, attach_shaft_to_head, make_shaft

_D_MINOR_VALUES = [2.0, 3.0, 4.0]
_L_VALUES = [10.0, 20.0, 35.0]
_TIP_VALUES = [2.0, 4.0]
_HEAD_ORDER = ["flat", "pan", "button", "hex"]
_HEAD_DEFAULTS: dict[str, HeadParams] = {
    "flat": {"type": "flat", "d": 8.0, "h": 4.0},
    "pan": {"type": "pan", "d": 8.0, "h": 4.0},
    "button": {"type": "button", "d": 8.0, "h": 4.0},
    "hex": {"type": "hex", "d": 8.0, "h": 4.0, "acrossFlats": 7.0},
}
_SPACING_HEAD_X = 70.0
_SPACING_L_X = 18.0
_SPACING_D_Y = 18.0
_SPACING_TIP_Y = 7.0


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v).replace(".", "p")


def _section_x_negative(solid: cq.Workplane) -> cq.Workplane:
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.2, 30.0)
    sy = max((bb.ymax - bb.ymin) * 1.5, 30.0)
    sz = max((bb.zmax - bb.zmin) * 1.5, 60.0)
    cutter = cq.Workplane("XY").box(sx, sy, sz, centered=(False, True, False)).translate((-sx, 0, bb.zmin - 0.25 * sz))
    return solid.intersect(cutter)


def _shaft_variants() -> list[ShaftParams]:
    variants: list[ShaftParams] = []
    for d_minor in _D_MINOR_VALUES:
        for L in _L_VALUES:
            for tip in _TIP_VALUES:
                if tip < L:
                    variants.append(ShaftParams(d_minor=d_minor, L=L, tip_len=tip))
    return variants


def build_screw_library_solids() -> list[cq.Workplane]:
    variants = _shaft_variants()
    out: list[cq.Workplane] = []
    for h_idx, head_name in enumerate(_HEAD_ORDER):
        head_params = _HEAD_DEFAULTS[head_name]
        head = make_head(head_params)
        for sp in variants:
            screw = attach_shaft_to_head(head, head_params, make_shaft(sp))
            d_idx = _D_MINOR_VALUES.index(sp.d_minor)
            L_idx = _L_VALUES.index(sp.L)
            tip_idx = _TIP_VALUES.index(sp.tip_len)
            x = h_idx * _SPACING_HEAD_X + L_idx * _SPACING_L_X
            y = d_idx * _SPACING_D_Y + tip_idx * _SPACING_TIP_Y
            out.append(screw.translate((x, y, 0)))
    return out


def export_screw_library(output_dir: Path | None = None) -> tuple[Path, Path, int]:
    solids = build_screw_library_solids()
    compound = cq.Compound.makeCompound([s.val() for s in solids])
    library_wp = cq.Workplane(obj=compound)
    if output_dir is None:
        library_path = export_step(library_wp, out_path("galleries", "step", "screw_library.step"))
        section_path = export_step(
            _section_x_negative(library_wp),
            out_path("galleries", "sectioned/step", "screw_library_section.step"),
        )
    else:
        library_path = export_step(library_wp, "screw_library.step", output_dir)
        section_path = export_step(_section_x_negative(library_wp), "screw_library_section.step", output_dir)
    return library_path, section_path, len(solids)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate shaft previews.")
    parser.add_argument("--stl", action="store_true", help="Export STL files.")
    parser.add_argument("--stl-tol", type=float, default=0.25, help="STL linear tolerance.")
    parser.add_argument("--stl-ang", type=float, default=0.35, help="STL angular tolerance.")
    args = parser.parse_args()

    print("Output root: out/\n")
    variants = _shaft_variants()
    print("== Shaft variants ==")
    for sp in variants:
        shaft = make_shaft(sp)
        base = f"shaft_d{_fmt(sp.d_minor)}_L{_fmt(sp.L)}_tip{_fmt(sp.tip_len)}"
        p_step = export_step(shaft, out_path("shafts", "step", f"{base}.step"))
        print(f"  [{base}] STEP -> {p_step}")
        if args.stl:
            p_stl = export_stl(
                shaft,
                out_path("shafts", "stl", f"{base}.stl"),
                tolerance=args.stl_tol,
                angular_tolerance=args.stl_ang,
            )
            print(f"  [{base}] STL  -> {p_stl}")

    print("\n== Head + shaft combinations (all heads) ==")
    for head_name in _HEAD_ORDER:
        head_params = _HEAD_DEFAULTS[head_name]
        head = make_head(head_params)
        for sp in variants:
            combo = attach_shaft_to_head(head, head_params, make_shaft(sp))
            combo_base = f"screw_{head_name}__dminor{_fmt(sp.d_minor)}_L{_fmt(sp.L)}_tip{_fmt(sp.tip_len)}"
            c_step = export_step(combo, out_path("screws", "step", f"{combo_base}.step"))
            print(f"  [{combo_base}] STEP -> {c_step}")
            if args.stl:
                c_stl = export_stl(
                    combo,
                    out_path("screws", "stl", f"{combo_base}.stl"),
                    tolerance=args.stl_tol,
                    angular_tolerance=args.stl_ang,
                )
                print(f"  [{combo_base}] STL  -> {c_stl}")

    library_path, section_path, count = export_screw_library()
    print(f"\n  screw_library.step -> {library_path}")
    print(f"  screw_library_section.step -> {section_path}")
    print(f"  solids in library: {count}")
    print("\nDone.")


if __name__ == "__main__":
    main()

