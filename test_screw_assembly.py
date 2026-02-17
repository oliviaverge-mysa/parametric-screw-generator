"""
Regression tests for head+drive+shaft screw assembly.
"""

from __future__ import annotations

import cadquery as cq
import pytest

from apply_drive import apply_drive_to_head
from drive import DriveParams
from head import HeadParams, head_tool_z, make_head
from preview_screws import export_gallery
from shaft import ShaftParams, attach_shaft_to_head, make_shaft, resolve_shaft_attach_z

_HEADS: list[HeadParams] = [
    {"type": "flat", "d": 8.0, "h": 4.0},
    {"type": "pan", "d": 8.0, "h": 4.0},
    {"type": "button", "d": 8.0, "h": 4.0},
    {"type": "hex", "d": 8.0, "h": 4.0, "acrossFlats": 7.0},
]
_SHAFT = ShaftParams(d_minor=3.0, L=20.0, tip_len=3.0)


def _make_drive(hp: HeadParams) -> DriveParams:
    return DriveParams(
        type="torx",
        size=6,
        depth=min(2.0, 0.45 * float(hp["h"])),
        topZ=head_tool_z(hp),
        fit="scale_to_head",
        head_d=float(hp["d"]),
    )


@pytest.mark.parametrize("hp", _HEADS, ids=[h["type"] for h in _HEADS])
def test_drive_cut_then_shaft_union(hp: HeadParams):
    head = make_head(hp)
    drive = _make_drive(hp)
    head_with_drive = apply_drive_to_head(head, drive, hp)
    screw = attach_shaft_to_head(head_with_drive, hp, make_shaft(_SHAFT))

    assert head_with_drive.val().Volume() < head.val().Volume()
    assert screw.val().Volume() > head_with_drive.val().Volume()
    assert screw.val().isValid()

    bb = screw.val().BoundingBox()
    assert bb.zmax > 0
    if hp["type"] == "flat":
        assert bb.zmin >= -0.05
    else:
        assert bb.zmin < 0


def test_flat_drive_opposite_shaft_side():
    hp: HeadParams = {"type": "flat", "d": 8.0, "h": 4.0}
    head = make_head(hp)
    driven = apply_drive_to_head(head, _make_drive(hp), hp)

    # Verify drive opening on the tool face side before shaft union (no interference).
    tool_open = driven.val().isInside(cq.Vector(0, 0, 0.02), 1e-6)
    shaft_side_closed = driven.val().isInside(cq.Vector(0, 0, float(hp["h"]) - 0.02), 1e-6)

    assert not tool_open
    assert shaft_side_closed

    # Flat shaft attachment should be near cone-match plane and extend outward.
    shaft = make_shaft(_SHAFT)
    shaft_radius = _SHAFT.d_minor / 2.0
    z_attach = resolve_shaft_attach_z(hp, shaft_radius)
    aligned = shaft.rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, z_attach - 0.05))
    abb = aligned.val().BoundingBox()
    assert abb.zmin == pytest.approx(z_attach - 0.05, abs=0.05)
    assert abb.zmax == pytest.approx(z_attach - 0.05 + _SHAFT.L, abs=0.05)


@pytest.mark.parametrize("hp", _HEADS[1:], ids=[h["type"] for h in _HEADS[1:]])
def test_non_flat_shaft_remains_below_head(hp: HeadParams):
    screw = attach_shaft_to_head(make_head(hp), hp, make_shaft(_SHAFT))
    bb = screw.val().BoundingBox()
    # Non-flat convention remains unchanged: shaft occupies negative Z.
    assert bb.zmin == pytest.approx(-_SHAFT.L + 0.05, abs=0.12)


def test_flat_seamless_attach_z_and_validity():
    hp: HeadParams = {"type": "flat", "d": 8.0, "h": 4.0}
    shaft = make_shaft(_SHAFT)
    z_attach = resolve_shaft_attach_z(hp, _SHAFT.d_minor / 2.0)
    screw = attach_shaft_to_head(make_head(hp), hp, shaft)
    assert screw.val().isValid()

    # Top of aligned shaft should sit near z_attach (with the configured overlap).
    aligned = shaft.rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, z_attach - 0.05))
    abb = aligned.val().BoundingBox()
    assert abb.zmin == pytest.approx(z_attach - 0.05, abs=0.05)


def test_screw_gallery_exports(tmp_path):
    gallery, section, count = export_gallery(tmp_path)
    # 4 heads x 3 drives x 2 shaft variants
    assert count == 24
    assert gallery.exists()
    assert section.exists()

