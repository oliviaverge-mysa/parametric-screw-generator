"""
Numeric tests for shaft generation and head+shaft attachment.

Run:
    python -m pytest test_shaft.py -v
"""

from __future__ import annotations

import cadquery as cq
import pytest

from head import HeadParams, make_head
from shaft import ShaftParams, attach_shaft_to_head, make_shaft

_TOL = 0.05


def _bbox(wp: cq.Workplane):
    return wp.val().BoundingBox()


def _volume(wp: cq.Workplane) -> float:
    return wp.val().Volume()


def _is_valid(wp: cq.Workplane) -> bool:
    return wp.val().isValid()


def _width_at_z(solid: cq.Workplane, z: float, slab_thickness: float = 0.04) -> float:
    bb = solid.val().BoundingBox()
    sx = (bb.xmax - bb.xmin) * 1.5 + 2.0
    sy = (bb.ymax - bb.ymin) * 1.5 + 2.0
    slab = cq.Workplane("XY").box(sx, sy, slab_thickness).translate((0, 0, z))
    sec = solid.intersect(slab)
    sbb = sec.val().BoundingBox()
    return max(sbb.xmax - sbb.xmin, sbb.ymax - sbb.ymin)


class TestShaftGeometry:
    def test_bbox_and_diameter(self):
        p = ShaftParams(d_minor=3.0, L=20.0, tip_len=4.0)
        shaft = make_shaft(p)
        bb = _bbox(shaft)
        assert bb.zmax == pytest.approx(0.0, abs=_TOL)
        assert bb.zmin == pytest.approx(-p.L, abs=_TOL)
        max_d = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
        assert max_d == pytest.approx(p.d_minor, rel=0.03)

    def test_tip_and_cylinder_regions_exist(self):
        p = ShaftParams(d_minor=4.0, L=35.0, tip_len=4.0)
        shaft = make_shaft(p)
        w_tip = _width_at_z(shaft, -p.L + 0.1)
        w_cyl = _width_at_z(shaft, -0.5 * (p.L - p.tip_len))
        assert w_tip > 0, "Expected finite geometry near the tip region"
        assert w_tip < p.d_minor * 0.4, "Tip section should be significantly narrower than cylinder"
        assert w_cyl == pytest.approx(p.d_minor, rel=0.04)

    def test_solid_valid(self):
        shaft = make_shaft(ShaftParams(d_minor=2.0, L=10.0, tip_len=2.0))
        assert _is_valid(shaft)
        assert _volume(shaft) > 0


class TestShaftValidation:
    def test_invalid_d_minor(self):
        with pytest.raises(ValueError, match="d_minor must be > 0"):
            make_shaft(ShaftParams(d_minor=0, L=10, tip_len=2))

    def test_invalid_L(self):
        with pytest.raises(ValueError, match="L must be > 0"):
            make_shaft(ShaftParams(d_minor=2, L=0, tip_len=2))

    def test_invalid_tip_len(self):
        with pytest.raises(ValueError, match="tip_len must be > 0"):
            make_shaft(ShaftParams(d_minor=2, L=10, tip_len=0))

    def test_tip_len_less_than_L(self):
        with pytest.raises(ValueError, match="tip_len must be < L"):
            make_shaft(ShaftParams(d_minor=2, L=10, tip_len=10))

    def test_angle_range(self):
        with pytest.raises(ValueError, match="tip_angle_deg must be in"):
            make_shaft(ShaftParams(d_minor=2, L=10, tip_len=2, tip_angle_deg=10))


class TestAttachment:
    def test_union_valid_and_volume_growth(self):
        head_params: HeadParams = {"type": "pan", "d": 8.0, "h": 4.0}
        head = make_head(head_params)
        shaft = make_shaft(ShaftParams(d_minor=3.0, L=20.0, tip_len=4.0))
        combo = attach_shaft_to_head(head, head_params, shaft)

        assert _is_valid(combo)
        assert _volume(combo) > _volume(head)
        assert _volume(combo) > _volume(shaft)

    def test_interface_continuity_near_z0(self):
        head_params: HeadParams = {"type": "pan", "d": 8.0, "h": 4.0}
        combo = attach_shaft_to_head(
            make_head(head_params),
            head_params,
            make_shaft(ShaftParams(d_minor=3.0, L=10.0, tip_len=2.0)),
        )
        inside_below = combo.val().isInside(cq.Vector(0, 0, -0.01), 1e-6)
        inside_above = combo.val().isInside(cq.Vector(0, 0, 0.01), 1e-6)
        assert inside_below, "Expected solid continuity just below Z=0 interface"
        assert inside_above, "Expected head material just above Z=0 interface"

