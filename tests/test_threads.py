from __future__ import annotations

import cadquery as cq
import pytest

from screwgen.assembly import make_screw_from_spec
from screwgen.shaft import ShaftParams, make_shaft
from screwgen.spec import DriveSpec, HeadSpec, ScrewSpec, ShaftSpec, SmoothRegionSpec, ThreadRegionSpec
from screwgen.threads import ThreadParams, apply_external_thread


def _width_at_z(solid: cq.Workplane, z: float, slab_thickness: float = 0.08) -> float:
    bb = solid.val().BoundingBox()
    sx = max((bb.xmax - bb.xmin) * 1.5, 20.0)
    sy = max((bb.ymax - bb.ymin) * 1.5, 20.0)
    slab = cq.Workplane("XY").box(sx, sy, slab_thickness).translate((0, 0, z))
    sec = solid.intersect(slab)
    sbb = sec.val().BoundingBox()
    return max(sbb.xmax - sbb.xmin, sbb.ymax - sbb.ymin)


def _core_shaft_plus_z(shaft_spec: ShaftSpec) -> cq.Workplane:
    shaft_local = make_shaft(
        ShaftParams(d_minor=shaft_spec.d_minor, L=shaft_spec.L, tip_len=shaft_spec.tip_len)
    )
    return shaft_local.rotate((0, 0, 0), (1, 0, 0), 180)


def test_thread_param_validation():
    shaft = ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0)
    core = _core_shaft_plus_z(shaft)
    with pytest.raises(ValueError, match="pitch must be > 0"):
        apply_external_thread(core, shaft, ThreadParams(pitch=0.0, length=10.0))
    with pytest.raises(ValueError, match="length must be > 0"):
        apply_external_thread(core, shaft, ThreadParams(pitch=1.0, length=0.0))
    with pytest.raises(ValueError, match="start_from_head must be >= 0"):
        apply_external_thread(core, shaft, ThreadParams(pitch=1.0, length=10.0, start_from_head=-1.0))
    # Thread length exceeding available space is clamped rather than rejected
    result = apply_external_thread(core, shaft, ThreadParams(pitch=1.0, length=27.0))
    assert result.val().isValid()


@pytest.mark.parametrize("mode", ["add", "cut"])
def test_apply_thread_increases_effective_major_diameter(mode: str):
    shaft = ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0)
    core = _core_shaft_plus_z(shaft)
    threaded = apply_external_thread(
        core,
        shaft,
        ThreadParams(pitch=1.0, length=20.0, start_from_head=2.0, mode=mode),  # type: ignore[arg-type]
    )
    bb = threaded.val().BoundingBox()
    max_d = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
    assert max_d > shaft.d_minor
    assert threaded.val().isValid()


def test_thread_does_not_extend_into_tip_region():
    shaft = ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0)
    core = _core_shaft_plus_z(shaft)
    threaded = apply_external_thread(
        core,
        shaft,
        ThreadParams(pitch=1.0, length=20.0, start_from_head=2.0, mode="cut"),
    )
    # Tip starts at z = L-tip_len = 26. Threaded span ends at z=22.
    width_near_unthreaded_cyl = _width_at_z(threaded, 24.0)
    assert width_near_unthreaded_cyl == pytest.approx(shaft.d_minor, rel=0.08)


def test_threaded_screw_spec_validity():
    spec = ScrewSpec(
        head=HeadSpec(type="pan", d=8.0, h=4.0),
        drive=DriveSpec(type="torx", size=6),
        shaft=ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0),
        regions=[
            SmoothRegionSpec(length=2.0),
            ThreadRegionSpec(length=20.0, pitch=1.0),
            SmoothRegionSpec(length=8.0),
        ],
    )
    screw = make_screw_from_spec(spec, include_thread_markers=False)
    assert screw.val().isValid()
    assert screw.val().Volume() > 0

