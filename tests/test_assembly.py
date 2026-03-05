from __future__ import annotations

import cadquery as cq
import pytest

from screwgen.assembly import apply_drive_to_head
from screwgen.drives import DriveParams
from screwgen.heads import HeadParams, head_tool_z, make_head
from screwgen.preview.preview_gallery import export_gallery
from screwgen.spec import DriveSpec, HeadSpec, ScrewSpec, ShaftSpec, SmoothRegionSpec
from screwgen.shaft import ShaftParams, attach_shaft_to_head, make_shaft, resolve_shaft_attach_z
from screwgen.assembly import make_screw

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
    head_with_drive = apply_drive_to_head(head, _make_drive(hp), hp)
    screw = attach_shaft_to_head(head_with_drive, hp, make_shaft(_SHAFT))
    assert head_with_drive.val().Volume() < head.val().Volume()
    assert screw.val().Volume() > head_with_drive.val().Volume()
    assert screw.val().isValid()


def test_flat_drive_opposite_shaft_side():
    hp: HeadParams = {"type": "flat", "d": 8.0, "h": 4.0}
    driven = apply_drive_to_head(make_head(hp), _make_drive(hp), hp)
    assert not driven.val().isInside(cq.Vector(0, 0, 0.02), 1e-6)
    assert driven.val().isInside(cq.Vector(0, 0, float(hp["h"]) - 0.02), 1e-6)
    shaft = make_shaft(_SHAFT)
    z_attach = resolve_shaft_attach_z(hp, _SHAFT.d_minor / 2.0)
    aligned = shaft.rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, z_attach - 0.05))
    abb = aligned.val().BoundingBox()
    assert abb.zmin == pytest.approx(z_attach - 0.05, abs=0.05)
    assert abb.zmax == pytest.approx(z_attach - 0.05 + _SHAFT.L, abs=0.05)


@pytest.mark.parametrize("hp", _HEADS[1:], ids=[h["type"] for h in _HEADS[1:]])
def test_non_flat_shaft_remains_below_head(hp: HeadParams):
    screw = attach_shaft_to_head(make_head(hp), hp, make_shaft(_SHAFT))
    assert screw.val().BoundingBox().zmin == pytest.approx(-_SHAFT.L + 0.05, abs=0.12)


def test_screw_gallery_exports(tmp_path):
    gallery, section, count = export_gallery(tmp_path)
    assert count == 32
    assert gallery.exists()
    assert section.exists()


def test_make_screw_accepts_screwspec():
    spec = ScrewSpec(
        head=HeadSpec(type="pan", d=8.0, h=4.0),
        drive=DriveSpec(type="torx", size=6),
        shaft=ShaftSpec(d_minor=3.0, L=20.0, tip_len=3.0),
        regions=[SmoothRegionSpec(length=20.0)],
    )
    screw = make_screw(spec)
    assert screw.val().isValid()

