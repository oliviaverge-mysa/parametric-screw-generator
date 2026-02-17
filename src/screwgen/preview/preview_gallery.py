"""Preview/export harness for representative head x drive x shaft screws."""

from __future__ import annotations

from pathlib import Path

import cadquery as cq

from ..assembly import apply_drive_to_head
from ..drives import DriveParams
from ..export import export_step, export_stl
from ..heads import HeadParams, head_tool_z, make_head
from ..shaft import ShaftParams, attach_shaft_to_head, make_shaft

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "outputs"
HEAD_TYPES = ["flat", "pan", "button", "hex"]
DRIVE_TYPES = [("hex", 3), ("phillips", 4), ("torx", 6)]
SHAFT_VARIANTS = {"A": ShaftParams(d_minor=3.0, L=20.0, tip_len=3.0), "B": ShaftParams(d_minor=4.0, L=35.0, tip_len=4.0)}


def _head_params(head_type: str) -> HeadParams:
    if head_type == "hex":
        return {"type": "hex", "d": 8.0, "h": 4.0, "acrossFlats": 7.0}
    return {"type": head_type, "d": 8.0, "h": 4.0}  # type: ignore[return-value]


def _drive_params(head_params: HeadParams, drive_type: str, size: int) -> DriveParams:
    h = float(head_params["h"])
    d = float(head_params["d"])
    return DriveParams(
        type=drive_type,  # type: ignore[arg-type]
        size=size,  # type: ignore[arg-type]
        depth=min(2.0, 0.45 * h),
        topZ=head_tool_z(head_params),
        fit="scale_to_head",
        head_d=d,
    )


def _section_x_negative(solid: cq.Workplane) -> cq.Workplane:
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.2, 40.0)
    sy = max((bb.ymax - bb.ymin) * 1.2, 40.0)
    sz = max((bb.zmax - bb.zmin) * 1.2, 40.0)
    cutter = cq.Workplane("XY").box(sx, sy, sz, centered=(False, True, False)).translate((-sx, 0, bb.zmin - 0.2 * sz))
    return solid.intersect(cutter)


def build_gallery_solids() -> list[cq.Workplane]:
    solids: list[cq.Workplane] = []
    expected = len(HEAD_TYPES) * len(DRIVE_TYPES) * len(SHAFT_VARIANTS)
    for h_idx, head_type in enumerate(HEAD_TYPES):
        hp = _head_params(head_type)
        head = make_head(hp)
        for d_idx, (dtype, dsize) in enumerate(DRIVE_TYPES):
            dp = _drive_params(hp, dtype, dsize)
            driven = apply_drive_to_head(head, dp, hp)
            for s_idx, (_, sp) in enumerate(SHAFT_VARIANTS.items()):
                screw = attach_shaft_to_head(driven, hp, make_shaft(sp))
                x = h_idx * 60.0 + s_idx * 20.0
                y = d_idx * 26.0
                solids.append(screw.translate((x, y, 0.0)))
    assert len(solids) == expected, f"Expected {expected} screws, got {len(solids)}"
    return solids


def export_gallery(output_dir: Path = OUTPUT_DIR) -> tuple[Path, Path, int]:
    solids = build_gallery_solids()
    comp = cq.Compound.makeCompound([s.val() for s in solids])
    wp = cq.Workplane(obj=comp)
    gallery = export_step(wp, "screw_gallery.step", output_dir)
    section = export_step(_section_x_negative(wp), "screw_gallery_section.step", output_dir)
    return gallery, section, len(solids)


def main() -> None:
    print(f"Output directory: {OUTPUT_DIR}\n")
    for head_type in HEAD_TYPES:
        hp = _head_params(head_type)
        head = make_head(hp)
        for dtype, dsize in DRIVE_TYPES:
            dp = _drive_params(hp, dtype, dsize)
            driven = apply_drive_to_head(head, dp, hp)
            for label, sp in SHAFT_VARIANTS.items():
                screw = attach_shaft_to_head(driven, hp, make_shaft(sp))
                base = f"screw_{head_type}__{dtype}__{label}"
                p_step = export_step(screw, f"{base}.step", OUTPUT_DIR)
                p_stl = export_stl(screw, f"{base}.stl", OUTPUT_DIR)
                print(f"  [{base}] STEP -> {p_step}")
                print(f"  [{base}] STL  -> {p_stl}")
    gallery, section, count = export_gallery(OUTPUT_DIR)
    print(f"\nGallery STEP -> {gallery}")
    print(f"Gallery section STEP -> {section}")
    print(f"Gallery screw count: {count}")
    print("\nDone.")


if __name__ == "__main__":
    main()

