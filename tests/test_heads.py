from __future__ import annotations

import math

import cadquery as cq
import pytest

from screwgen.heads import HeadParams, make_head

_TOL = 0.05


def _bbox(solid: cq.Workplane):
    return solid.val().BoundingBox()


def _is_valid(solid: cq.Workplane) -> bool:
    return solid.val().isValid()


def _width_at_z(solid: cq.Workplane, z: float, slab_thickness: float = 0.02) -> float:
    bb = solid.val().BoundingBox()
    sx = (bb.xmax - bb.xmin) * 1.5 + 2.0
    sy = (bb.ymax - bb.ymin) * 1.5 + 2.0
    slab = cq.Workplane("XY").box(sx, sy, slab_thickness).translate((0, 0, z))
    sec = solid.intersect(slab)
    sec_bb = sec.val().BoundingBox()
    return max(sec_bb.xmax - sec_bb.xmin, sec_bb.ymax - sec_bb.ymin)


_D = 8.0
_H = 4.0
_AF = 7.0
_SPECS: list[tuple[str, HeadParams, float]] = [
    ("flat", {"type": "flat", "d": _D, "h": _H}, _D),
    ("pan", {"type": "pan", "d": _D, "h": _H}, _D),
    ("button", {"type": "button", "d": _D, "h": _H}, _D),
    ("hex", {"type": "hex", "d": _D, "h": _H, "acrossFlats": _AF}, _AF / math.cos(math.radians(30))),
]


@pytest.mark.parametrize("label,params,expected_width", _SPECS, ids=[s[0] for s in _SPECS])
class TestHeadGeometry:
    def test_z_min_is_zero(self, label, params, expected_width):
        assert _bbox(make_head(params)).zmin == pytest.approx(0.0, abs=_TOL)

    def test_z_max_is_h(self, label, params, expected_width):
        assert _bbox(make_head(params)).zmax == pytest.approx(params["h"], abs=_TOL)

    def test_max_width(self, label, params, expected_width):
        bb = _bbox(make_head(params))
        actual = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
        assert actual == pytest.approx(expected_width, rel=0.02)

    def test_volume_positive(self, label, params, expected_width):
        assert make_head(params).val().Volume() > 0

    def test_solid_valid(self, label, params, expected_width):
        assert _is_valid(make_head(params))


class TestFlatTopLand:
    _params: HeadParams = {"type": "flat", "d": _D, "h": _H}

    def test_top_face_exists_with_nonzero_area(self):
        assert make_head(self._params).faces(">Z").val().Area() > 0

    def test_top_land_diameter(self):
        expected_top_d = max(0.05 * _D, 0.2)
        expected_area = math.pi * (expected_top_d / 2.0) ** 2
        area = make_head(self._params).faces(">Z").val().Area()
        assert area == pytest.approx(expected_area, rel=0.05)

    def test_flat_frustum_is_wide_at_underside_and_narrow_at_top(self):
        solid = make_head(self._params)
        width_bottom = _width_at_z(solid, 0.01)
        width_top = _width_at_z(solid, _H - 0.01)
        expected_top_d = max(0.05 * _D, 0.2)
        assert width_bottom == pytest.approx(_D, rel=0.03)
        assert width_top == pytest.approx(expected_top_d, rel=0.12)
        assert width_bottom > width_top


class TestValidation:
    def test_invalid_type(self):
        with pytest.raises(ValueError, match="Unknown head type"):
            make_head({"type": "torx", "d": 8, "h": 4})  # type: ignore[arg-type]

    def test_d_zero(self):
        with pytest.raises(ValueError, match="d must be > 0"):
            make_head({"type": "flat", "d": 0, "h": 4})

    def test_h_zero(self):
        with pytest.raises(ValueError, match="h must be > 0"):
            make_head({"type": "flat", "d": 8, "h": 0})


class TestDeterminism:
    @pytest.mark.parametrize("params", [s[1] for s in _SPECS], ids=[s[0] for s in _SPECS])
    def test_volume_deterministic(self, params):
        assert make_head(params).val().Volume() == pytest.approx(make_head(params).val().Volume(), rel=1e-9)

