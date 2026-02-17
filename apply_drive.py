"""
Apply a drive recess cut to a screw head.

Kept separate from both head.py and drive.py so that each module
can be used and tested independently.
"""

from __future__ import annotations

from dataclasses import replace

import cadquery as cq

from drive import DriveParams, make_drive_cut
from head import HeadParams, head_tool_z


def apply_drive_to_head(
    head: cq.Workplane,
    p: DriveParams,
    head_params: HeadParams | None = None,
) -> cq.Workplane:
    """Subtract the drive recess from *head* and return the result.

    Drive placement is referenced to the head's explicit tool-side convention.
    """
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
        # Drive generator is -Z oriented; flat tool face is at Z=0 and
        # recess must enter +Z, so mirror across XY.
        cut = cut.mirror("XY")
    return head.cut(cut)
