"""
Numeric tests for the drive-recess generator.

Verifies bounding-box geometry, volume, solid validity, and that boolean
subtraction from each head type produces a smaller, valid solid.

Run:
    python -m pytest test_drive.py -v
"""

from __future__ import annotations

import math

import cadquery as cq
import pytest

from drive import DriveParams, make_drive_cut
from head import HeadParams, head_tool_z, make_head
from apply_drive import apply_drive_to_head

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOL = 0.10  # mm — bounding-box tolerance (larger than head tests because
              #       polygon approximations widen the bbox slightly)


def _bbox(wp: cq.Workplane):
    return wp.val().BoundingBox()


def _volume(wp: cq.Workplane) -> float:
    return wp.val().Volume()


def _is_valid(wp: cq.Workplane) -> bool:
    return wp.val().isValid()


# ---------------------------------------------------------------------------
# Shared parameters
# ---------------------------------------------------------------------------

_D = 8.0
_H = 4.0
_DEPTH = min(2.0, 0.45 * _H)   # same formula as preview harness
_TOP_Z = _H

_DRIVE_PARAMS: list[DriveParams] = [
    DriveParams(type="hex",      size=3, depth=_DEPTH, topZ=_TOP_Z, fit="scale_to_head", head_d=_D),
    DriveParams(type="phillips", size=4, depth=_DEPTH, topZ=_TOP_Z, fit="scale_to_head", head_d=_D),
    DriveParams(type="torx",     size=6, depth=_DEPTH, topZ=_TOP_Z, fit="scale_to_head", head_d=_D),
]

_DRIVE_IDS = ["hex_3", "phillips_4", "torx_6"]

_HEAD_SPECS: list[HeadParams] = [
    {"type": "flat",   "d": _D, "h": _H},
    {"type": "pan",    "d": _D, "h": _H},
    {"type": "button", "d": _D, "h": _H},
    {"type": "hex",    "d": _D, "h": _H, "acrossFlats": 7.0},
]

_HEAD_IDS = ["flat", "pan", "button", "hex"]


# ---------------------------------------------------------------------------
# Drive cut geometry tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dp", _DRIVE_PARAMS, ids=_DRIVE_IDS)
class TestDriveCutGeometry:
    """Bounding-box and volume sanity for each drive cut solid."""

    def test_z_min(self, dp: DriveParams):
        """Cut bottom should be at topZ - depth - eps."""
        cut = make_drive_cut(dp)
        bb = _bbox(cut)
        expected = dp.topZ - dp.depth - dp.eps
        assert bb.zmin == pytest.approx(expected, abs=_TOL), (
            f"Z min = {bb.zmin}, expected {expected}"
        )

    def test_z_max(self, dp: DriveParams):
        """Cut top should be at topZ + eps."""
        cut = make_drive_cut(dp)
        bb = _bbox(cut)
        expected = dp.topZ + dp.eps
        assert bb.zmax == pytest.approx(expected, abs=_TOL), (
            f"Z max = {bb.zmax}, expected {expected}"
        )

    def test_volume_positive(self, dp: DriveParams):
        cut = make_drive_cut(dp)
        assert _volume(cut) > 0

    def test_solid_valid(self, dp: DriveParams):
        cut = make_drive_cut(dp)
        assert _is_valid(cut)


# ---------------------------------------------------------------------------
# Drive validation tests
# ---------------------------------------------------------------------------


class TestDriveValidation:
    """Parameter validation must reject bad inputs."""

    def test_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown drive type"):
            make_drive_cut(
                DriveParams(type="slot", size=3, depth=1.0, topZ=4.0)  # type: ignore[arg-type]
            )

    def test_wrong_size_for_hex(self):
        with pytest.raises(ValueError, match="requires size=3"):
            make_drive_cut(
                DriveParams(type="hex", size=6, depth=1.0, topZ=4.0)  # type: ignore[arg-type]
            )

    def test_wrong_size_for_phillips(self):
        with pytest.raises(ValueError, match="requires size=4"):
            make_drive_cut(
                DriveParams(type="phillips", size=3, depth=1.0, topZ=4.0)  # type: ignore[arg-type]
            )

    def test_wrong_size_for_torx(self):
        with pytest.raises(ValueError, match="requires size=6"):
            make_drive_cut(
                DriveParams(type="torx", size=3, depth=1.0, topZ=4.0)  # type: ignore[arg-type]
            )

    def test_depth_zero(self):
        with pytest.raises(ValueError, match="depth must be > 0"):
            make_drive_cut(
                DriveParams(type="hex", size=3, depth=0, topZ=4.0)
            )

    def test_topZ_zero(self):
        with pytest.raises(ValueError, match="topZ must be > 0"):
            make_drive_cut(
                DriveParams(type="hex", size=3, depth=1.0, topZ=0)
            )

    def test_scale_fit_requires_head_d(self):
        with pytest.raises(ValueError, match="requires head_d > 0"):
            make_drive_cut(
                DriveParams(type="hex", size=3, depth=1.0, topZ=4.0, fit="scale_to_head")
            )


# ---------------------------------------------------------------------------
# Head + drive boolean tests
# ---------------------------------------------------------------------------

# Build all (head, drive) combos for parametrize.
_COMBO_PARAMS = [
    (hspec, dp)
    for hspec in _HEAD_SPECS
    for dp in _DRIVE_PARAMS
]
_COMBO_IDS = [
    f"{hspec['type']}__{dp.type}_{dp.size}"
    for hspec in _HEAD_SPECS
    for dp in _DRIVE_PARAMS
]


@pytest.mark.parametrize("hspec,dp", _COMBO_PARAMS, ids=_COMBO_IDS)
class TestHeadDriveCombos:
    """After subtracting a drive recess, the head must shrink and stay valid."""

    def test_volume_decreases(self, hspec: HeadParams, dp: DriveParams):
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
        v_before = _volume(head)
        v_after = _volume(combo)
        assert v_after < v_before, (
            f"Volume did not decrease: {v_before} -> {v_after}"
        )

    def test_solid_valid_after_cut(self, hspec: HeadParams, dp: DriveParams):
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
        assert _is_valid(combo), "Solid invalid after drive cut"


class TestFlatDrivePlacement:
    """Flat-head drive must be on tool side at Z=0."""

    def test_flat_underside_center_remains_inside(self):
        hspec: HeadParams = {"type": "flat", "d": _D, "h": _H}
        head = make_head(hspec)
        dp = DriveParams(type="torx", size=6, depth=_DEPTH, topZ=head_tool_z(hspec), fit="scale_to_head", head_d=_D)
        combo = apply_drive_to_head(head, dp, hspec)
        inside_bottom_center = combo.val().isInside(cq.Vector(0, 0, 0.02), 1e-6)
        assert not inside_bottom_center, "Flat tool face at Z=0 should have drive opening."

    def test_flat_back_face_is_not_open(self):
        hspec: HeadParams = {"type": "flat", "d": _D, "h": _H}
        head = make_head(hspec)
        dp = DriveParams(type="hex", size=3, depth=_DEPTH, topZ=head_tool_z(hspec), fit="scale_to_head", head_d=_D)
        combo = apply_drive_to_head(head, dp, hspec)
        inside_back_center = combo.val().isInside(cq.Vector(0, 0, _H - 0.02), 1e-6)
        assert inside_back_center, "Flat back face near Z=h should remain uncut."


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dp", _DRIVE_PARAMS, ids=_DRIVE_IDS)
class TestDriveDeterminism:
    """Identical params must produce identical volume."""

    def test_volume_deterministic(self, dp: DriveParams):
        v1 = _volume(make_drive_cut(dp))
        v2 = _volume(make_drive_cut(dp))
        assert v1 == pytest.approx(v2, rel=1e-9)
