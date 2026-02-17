"""
Head + drive + shaft assembly helpers.

No thread geometry included.
"""

from __future__ import annotations

import cadquery as cq

from apply_drive import apply_drive_to_head
from drive import DriveParams
from head import HeadParams, make_head
from shaft import ShaftParams, attach_shaft_to_head, make_shaft


def make_screw(head_params: HeadParams, drive_params: DriveParams, shaft_params: ShaftParams) -> cq.Workplane:
    """Build a screw as head -> drive-cut head -> unioned shaft."""
    head = make_head(head_params)
    head_with_drive = apply_drive_to_head(head, drive_params, head_params)
    shaft = make_shaft(shaft_params)
    return attach_shaft_to_head(head_with_drive, head_params, shaft)

