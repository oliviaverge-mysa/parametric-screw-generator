"""
Numeric tests for the screw-head generator.

Verifies bounding-box geometry, volume, and solid validity for every head type.
No visual inspection required.

Run:
    python -m pytest test_head.py -v
"""

from __future__ import annotations

import math

import cadquery as cq
import pytest

from head import HeadParams, make_head

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOL = 0.05  # mm — geometric tolerance for bounding-box checks


def _bbox(solid: cq.Workplane):
    """Return the bounding box of the first solid in the workplane."""
    bb = solid.val().BoundingBox()
    return bb


def _is_valid(solid: cq.Workplane) -> bool:
    """Return True if the underlying shape is a valid solid."""
    shape = solid.val()
    return shape.isValid()


def _width_at_z(solid: cq.Workplane, z: float, slab_thickness: float = 0.02) -> float:
    """Approximate XY width by intersecting with a thin Z-slab at *z*."""
    bb = solid.val().BoundingBox()
    sx = (bb.xmax - bb.xmin) * 1.5 + 2.0
    sy = (bb.ymax - bb.ymin) * 1.5 + 2.0
    slab = (
        cq.Workplane("XY")
        .box(sx, sy, slab_thickness)
        .translate((0, 0, z))
    )
    sec = solid.intersect(slab)
    sec_bb = sec.val().BoundingBox()
    return max(sec_bb.xmax - sec_bb.xmin, sec_bb.ymax - sec_bb.ymin)


# ---------------------------------------------------------------------------
# Test parameters
# ---------------------------------------------------------------------------

_D = 8.0
_H = 4.0
_AF = 7.0  # hex across-flats

_SPECS: list[tuple[str, HeadParams, float]] = [
    # (label, params, expected_max_width)
    ("flat",   {"type": "flat",   "d": _D, "h": _H}, _D),
    ("pan",    {"type": "pan",    "d": _D, "h": _H}, _D),
    ("button", {"type": "button", "d": _D, "h": _H}, _D),
    ("hex",    {"type": "hex",    "d": _D, "h": _H, "acrossFlats": _AF},
     _AF / math.cos(math.radians(30))),  # vertex-to-vertex diameter
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,params,expected_width", _SPECS, ids=[s[0] for s in _SPECS])
class TestHeadGeometry:
    """Geometric sanity checks for each head type."""

    def test_z_min_is_zero(self, label, params, expected_width):
        solid = make_head(params)
        bb = _bbox(solid)
        assert bb.zmin == pytest.approx(0.0, abs=_TOL), (
            f"{label}: Z min = {bb.zmin}, expected 0"
        )

    def test_z_max_is_h(self, label, params, expected_width):
        solid = make_head(params)
        bb = _bbox(solid)
        assert bb.zmax == pytest.approx(params["h"], abs=_TOL), (
            f"{label}: Z max = {bb.zmax}, expected {params['h']}"
        )

    def test_max_width(self, label, params, expected_width):
        solid = make_head(params)
        bb = _bbox(solid)
        # Width in XY plane
        actual_width_x = bb.xmax - bb.xmin
        actual_width_y = bb.ymax - bb.ymin
        actual_max = max(actual_width_x, actual_width_y)
        assert actual_max == pytest.approx(expected_width, rel=0.02), (
            f"{label}: max width = {actual_max}, expected ≈ {expected_width}"
        )

    def test_volume_positive(self, label, params, expected_width):
        solid = make_head(params)
        vol = solid.val().Volume()
        assert vol > 0, f"{label}: volume = {vol}, expected > 0"

    def test_solid_valid(self, label, params, expected_width):
        solid = make_head(params)
        assert _is_valid(solid), f"{label}: solid is not valid"


# ---------------------------------------------------------------------------
# Flat head top-land tests
# ---------------------------------------------------------------------------


class TestFlatTopLand:
    """Verify the flat head frustum has a real top face (non-zero area)."""

    _params: HeadParams = {"type": "flat", "d": _D, "h": _H}

    def test_z_min_is_zero(self):
        solid = make_head(self._params)
        bb = _bbox(solid)
        assert bb.zmin == pytest.approx(0.0, abs=_TOL)

    def test_z_max_is_h(self):
        solid = make_head(self._params)
        bb = _bbox(solid)
        assert bb.zmax == pytest.approx(_H, abs=_TOL)

    def test_base_diameter_is_d(self):
        """Max XY extent (at Z=0) should equal d."""
        solid = make_head(self._params)
        bb = _bbox(solid)
        actual = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
        assert actual == pytest.approx(_D, rel=0.02)

    def test_top_face_exists_with_nonzero_area(self):
        """The top face at Z=h must be a real circular land, not a point."""
        solid = make_head(self._params)
        # Select the highest face (Z = h).
        top_faces = solid.faces(">Z")
        top_face = top_faces.val()
        area = top_face.Area()
        assert area > 0, f"Top face area = {area}, expected > 0"

    def test_top_land_diameter(self):
        """The top land diameter should match max(0.05*d, 0.2)."""
        expected_top_d = max(0.05 * _D, 0.2)
        expected_area = math.pi * (expected_top_d / 2.0) ** 2
        solid = make_head(self._params)
        top_face = solid.faces(">Z").val()
        area = top_face.Area()
        assert area == pytest.approx(expected_area, rel=0.05), (
            f"Top face area {area} != expected {expected_area}"
        )

    def test_solid_valid(self):
        solid = make_head(self._params)
        assert _is_valid(solid)

    def test_flat_frustum_is_wide_at_underside_and_narrow_at_top(self):
        """Flat head must be large near Z=0 and small near Z=h."""
        solid = make_head(self._params)
        z_bottom = 0.01
        z_top = _H - 0.01
        width_bottom = _width_at_z(solid, z_bottom)
        width_top = _width_at_z(solid, z_top)
        expected_top_d = max(0.05 * _D, 0.2)

        assert width_bottom == pytest.approx(_D, rel=0.03), (
            f"Bottom-section width {width_bottom} != expected {_D}"
        )
        assert width_top == pytest.approx(expected_top_d, rel=0.12), (
            f"Top-section width {width_top} != expected {expected_top_d}"
        )
        assert width_bottom > width_top, "Flat frustum should narrow upward."


# ---------------------------------------------------------------------------
# Validation error tests
# ---------------------------------------------------------------------------


class TestValidation:
    """Parameter validation must reject bad inputs."""

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="Unknown head type"):
            make_head({"type": "torx", "d": 8, "h": 4})

    def test_d_zero(self):
        with pytest.raises(ValueError, match="d must be > 0"):
            make_head({"type": "flat", "d": 0, "h": 4})

    def test_d_negative(self):
        with pytest.raises(ValueError, match="d must be > 0"):
            make_head({"type": "flat", "d": -1, "h": 4})

    def test_h_zero(self):
        with pytest.raises(ValueError, match="h must be > 0"):
            make_head({"type": "flat", "d": 8, "h": 0})

    def test_across_flats_negative(self):
        with pytest.raises(ValueError, match="acrossFlats must be > 0"):
            make_head({"type": "hex", "d": 8, "h": 4, "acrossFlats": -1})


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Two calls with identical params must produce identical geometry."""

    @pytest.mark.parametrize("params", [s[1] for s in _SPECS], ids=[s[0] for s in _SPECS])
    def test_volume_deterministic(self, params):
        v1 = make_head(params).val().Volume()
        v2 = make_head(params).val().Volume()
        assert v1 == pytest.approx(v2, rel=1e-9)
