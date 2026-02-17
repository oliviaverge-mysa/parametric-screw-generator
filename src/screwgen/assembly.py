"""Assembly helpers for head + drive + shaft."""

from __future__ import annotations

from dataclasses import replace

import cadquery as cq

from .drives import DriveParams, make_drive_cut
from .heads import HeadParams, head_tool_z, make_head
from .shaft import ShaftParams, attach_shaft_to_head, make_shaft


def apply_drive_to_head(head: cq.Workplane, p: DriveParams, head_params: HeadParams | None = None) -> cq.Workplane:
    bb = head.val().BoundingBox()
    inferred_head_d = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
    tool_z = head_tool_z(head_params) if head_params is not None else bb.zmax
    is_flat = head_params is not None and head_params["type"] == "flat"
    p_effective = replace(
        p,
        topZ=(max(tool_z, p.eps) if is_flat else tool_z),
        head_d=(p.head_d if p.head_d is not None else inferred_head_d),
    )
    cut = make_drive_cut(p_effective)
    if is_flat:
        cut = cut.mirror("XY")
    return head.cut(cut)


def make_screw(head_params: HeadParams, drive_params: DriveParams, shaft_params: ShaftParams) -> cq.Workplane:
    head = make_head(head_params)
    head_with_drive = apply_drive_to_head(head, drive_params, head_params)
    shaft = make_shaft(shaft_params)
    return attach_shaft_to_head(head_with_drive, head_params, shaft)

