from __future__ import annotations

import cadquery as cq
import pytest

from screwgen.assembly import apply_drive_to_head
from screwgen.drives import DriveParams, make_drive_cut
from screwgen.heads import HeadParams, head_tool_z, make_head

_TOL = 0.10
_D = 8.0
_H = 4.0
_DEPTH = min(2.0, 0.45 * _H)
_TOP_Z = _H


def _bbox(wp: cq.Workplane):
    return wp.val().BoundingBox()


def _volume(wp: cq.Workplane) -> float:
    return wp.val().Volume()


def _is_valid(wp: cq.Workplane) -> bool:
    return wp.val().isValid()


_DRIVE_PARAMS = [
    DriveParams(type="hex", size=3, depth=_DEPTH, topZ=_TOP_Z, fit="scale_to_head", head_d=_D),
    DriveParams(type="phillips", size=4, depth=_DEPTH, topZ=_TOP_Z, fit="scale_to_head", head_d=_D),
    DriveParams(type="square", size=5, depth=_DEPTH, topZ=_TOP_Z, fit="scale_to_head", head_d=_D),
    DriveParams(type="torx", size=6, depth=_DEPTH, topZ=_TOP_Z, fit="scale_to_head", head_d=_D),
]
_HEAD_SPECS: list[HeadParams] = [
    {"type": "flat", "d": _D, "h": _H},
    {"type": "pan", "d": _D, "h": _H},
    {"type": "button", "d": _D, "h": _H},
    {"type": "hex", "d": _D, "h": _H, "acrossFlats": 7.0},
]


@pytest.mark.parametrize("dp", _DRIVE_PARAMS, ids=["hex_3", "phillips_4", "square_5", "torx_6"])
class TestDriveCutGeometry:
    def test_z_span(self, dp: DriveParams):
        bb = _bbox(make_drive_cut(dp))
        assert bb.zmin == pytest.approx(dp.topZ - dp.depth - dp.eps, abs=_TOL)
        assert bb.zmax == pytest.approx(dp.topZ + dp.eps, abs=_TOL)

    def test_volume_positive(self, dp: DriveParams):
        assert _volume(make_drive_cut(dp)) > 0

    def test_solid_valid(self, dp: DriveParams):
        assert _is_valid(make_drive_cut(dp))


@pytest.mark.parametrize(
    "hspec,dp",
    [(h, d) for h in _HEAD_SPECS for d in _DRIVE_PARAMS],
    ids=[f"{h['type']}__{d.type}_{d.size}" for h in _HEAD_SPECS for d in _DRIVE_PARAMS],
)
def test_head_drive_volume_decreases_and_valid(hspec: HeadParams, dp: DriveParams):
    head = make_head(hspec)
    p_local = DriveParams(
        type=dp.type,
        size=dp.size,
        depth=dp.depth,
        topZ=head_tool_z(hspec),
        clearance=dp.clearance,
        eps=dp.eps,
        fit=dp.fit,
        head_d=hspec["d"],
        min_wall=dp.min_wall,
    )
    combo = apply_drive_to_head(head, p_local, hspec)
    assert _volume(combo) < _volume(head)
    assert _is_valid(combo)


class TestFlatDrivePlacement:
    def test_flat_opening_on_z0_not_zh(self):
        hspec: HeadParams = {"type": "flat", "d": _D, "h": _H}
        head = make_head(hspec)
        dp = DriveParams(type="hex", size=3, depth=_DEPTH, topZ=head_tool_z(hspec), fit="scale_to_head", head_d=_D)
        combo = apply_drive_to_head(head, dp, hspec)
        assert not combo.val().isInside(cq.Vector(0, 0, 0.02), 1e-6)
        assert combo.val().isInside(cq.Vector(0, 0, _H - 0.02), 1e-6)

