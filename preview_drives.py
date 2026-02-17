"""
Preview harness for drive recesses and head+drive combinations.

Exports:
1) Drive-only cut solids (STEP + STL).
2) Head+drive combos across multiple head sizes (STEP + STL).
3) Section-view exports for debugging recess depth profile.
4) Combined gallery STEP of all combos for quick visual inspection.

Run:
    python preview_drives.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

import cadquery as cq

from head import HeadParams, head_tool_z, make_head
from drive import DriveParams, make_drive_cut
from apply_drive import apply_drive_to_head
from export import export_step, export_stl

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"

_HEAD_SIZES: list[tuple[float, float]] = [
    (6.0, 3.0),
    (8.0, 4.0),
    (12.0, 6.0),
]
_HEAD_TYPES = ("flat", "pan", "button", "hex")

_GALLERY_SPACING_X = 18.0   # mm
_GALLERY_SPACING_Y = 18.0   # mm


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
    """Keep X<=0 half for section view visualization."""
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.2, 20.0)
    sy = max((bb.ymax - bb.ymin) * 1.5, 20.0)
    sz = max((bb.zmax - bb.zmin) * 1.5, 20.0)
    cutter = (
        cq.Workplane("XY")
        .box(sx, sy, sz, centered=(False, True, False))
        .translate((-sx, 0, bb.zmin - 0.25 * sz))
    )
    return solid.intersect(cutter)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Output directory: {OUTPUT_DIR}\n")

    # ------------------------------------------------------------------
    # 1) Drive-only exports
    # ------------------------------------------------------------------
    print("== Drive-only solids ==")
    # Use d=8,h=4 for drive-only reference exports.
    ref_head = _head_spec("pan", 8.0, 4.0)
    for dp in _drive_specs_for_head(ref_head):
        cut = make_drive_cut(dp)
        label = f"{dp.type}_{dp.size}"
        sp = export_step(cut, f"drive_{label}.step", OUTPUT_DIR)
        tp = export_stl(cut, f"drive_{label}.stl", OUTPUT_DIR, tolerance=0.05, angular_tolerance=0.2)
        print(f"  [{label:>12}]  STEP -> {sp}")
        print(f"  [{label:>12}]  STL  -> {tp}")

    # ------------------------------------------------------------------
    # 2) Head + drive combos across sizes
    # ------------------------------------------------------------------
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
                sp = export_step(combo, f"{fname_base}.step", OUTPUT_DIR)
                tp = export_stl(combo, f"{fname_base}.stl", OUTPUT_DIR, tolerance=0.05, angular_tolerance=0.2)
                print(f"  [{label:>22}]  STEP -> {sp}")
                print(f"  [{label:>22}]  STL  -> {tp}")

                # Section-view debug export to make recess depth profile visible.
                section = _section_half_x_negative(combo)
                section_name = f"head_{htype}__{dp.type}_section_d{int(d)}"
                sp_section = export_step(section, f"{section_name}.step", OUTPUT_DIR)
                print(f"  [{label:>22}]  SECTION -> {sp_section}")

    # ------------------------------------------------------------------
    # 3) Gallery STEP
    # ------------------------------------------------------------------
    print("\nBuilding combo gallery...")
    gallery = cq.Assembly()
    columns = 12  # 3 sizes x 4 head types

    for idx, (label, solid) in enumerate(combo_solids):
        row = idx // columns
        col = idx % columns
        x = col * _GALLERY_SPACING_X
        y = row * _GALLERY_SPACING_Y
        gallery.add(
            solid,
            name=label,
            loc=cq.Location(cq.Vector(x, y, 0)),
        )

    gallery_path = OUTPUT_DIR / "drive_combo_gallery.step"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        gallery.save(str(gallery_path), exportType="STEP")
    print(f"  Gallery STEP -> {gallery_path.resolve()}")

    print("\nDone.")


if __name__ == "__main__":
    main()
