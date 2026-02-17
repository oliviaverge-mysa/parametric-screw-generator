from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from screwgen.heads import HeadParams, make_head
from screwgen.preview.preview_shafts import _HEAD_ORDER, _shaft_variants, export_screw_library
from screwgen.shaft import ShaftParams, attach_shaft_to_head, make_shaft

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
        assert max(bb.xmax - bb.xmin, bb.ymax - bb.ymin) == pytest.approx(p.d_minor, rel=0.03)

    def test_tip_and_cylinder_regions_exist(self):
        p = ShaftParams(d_minor=4.0, L=35.0, tip_len=4.0)
        shaft = make_shaft(p)
        assert 0 < _width_at_z(shaft, -p.L + 0.1) < p.d_minor * 0.4
        assert _width_at_z(shaft, -0.5 * (p.L - p.tip_len)) == pytest.approx(p.d_minor, rel=0.04)

    def test_attachment_valid_and_volume_growth(self):
        head_params: HeadParams = {"type": "pan", "d": 8.0, "h": 4.0}
        head = make_head(head_params)
        shaft = make_shaft(ShaftParams(d_minor=3.0, L=20.0, tip_len=4.0))
        combo = attach_shaft_to_head(head, head_params, shaft)
        assert _is_valid(combo)
        assert _volume(combo) > _volume(head)
        assert _volume(combo) > _volume(shaft)


def test_screw_library_export_and_count(tmp_path: Path):
    library_path, section_path, solid_count = export_screw_library(tmp_path)
    assert solid_count == len(_HEAD_ORDER) * len(_shaft_variants())
    assert library_path.exists()
    assert section_path.exists()

