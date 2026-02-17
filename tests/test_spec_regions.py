from __future__ import annotations

import pytest

from screwgen.assembly import build_thread_region_markers, make_screw_from_spec, shaft_axis_for_head
from screwgen.spec import (
    DriveSpec,
    HeadSpec,
    ScrewSpec,
    ShaftSpec,
    SmoothRegionSpec,
    ThreadRegionSpec,
    expand_regions,
    validate_screw_spec,
)


def _base_spec(head_type: str = "pan") -> ScrewSpec:
    return ScrewSpec(
        head=HeadSpec(type=head_type, d=8.0, h=4.0, acrossFlats=7.0 if head_type == "hex" else None),
        drive=DriveSpec(type="hex", size=3),
        shaft=ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0),
        regions=[
            ThreadRegionSpec(length=10.0, pitch=1.0),
            SmoothRegionSpec(length=5.0),
            ThreadRegionSpec(length=10.0, pitch=1.0),
        ],
    )


class TestSpecValidation:
    def test_regions_cannot_exceed_shaft_length(self):
        spec = ScrewSpec(
            head=HeadSpec(type="pan", d=8.0, h=4.0),
            drive=None,
            shaft=ShaftSpec(d_minor=4.0, L=10.0, tip_len=2.0),
            regions=[SmoothRegionSpec(length=6.0), ThreadRegionSpec(length=6.0, pitch=1.0)],
        )
        with pytest.raises(ValueError, match="sum\\(region.length\\) must be <="):
            validate_screw_spec(spec)

    def test_region_lengths_must_be_positive(self):
        spec = ScrewSpec(
            head=HeadSpec(type="pan", d=8.0, h=4.0),
            drive=None,
            shaft=ShaftSpec(d_minor=4.0, L=10.0, tip_len=2.0),
            regions=[SmoothRegionSpec(length=0.0)],
        )
        with pytest.raises(ValueError, match="regions\\[0\\]\\.length must be > 0"):
            validate_screw_spec(spec)

    def test_expand_regions_appends_smooth_tail(self):
        spec = ScrewSpec(
            head=HeadSpec(type="pan", d=8.0, h=4.0),
            drive=None,
            shaft=ShaftSpec(d_minor=4.0, L=10.0, tip_len=2.0),
            regions=[ThreadRegionSpec(length=4.0, pitch=1.0)],
        )
        expanded = expand_regions(spec)
        assert len(expanded) == 2
        assert isinstance(expanded[-1], SmoothRegionSpec)
        assert expanded[-1].length == pytest.approx(6.0, abs=1e-9)


@pytest.mark.parametrize("head_type", ["pan", "flat"])
def test_thread_marker_bbox_matches_region_axis(head_type: str):
    spec = _base_spec(head_type=head_type)
    validate_screw_spec(spec)
    markers = build_thread_region_markers(spec)
    assert markers is not None
    bb = markers.val().BoundingBox()

    head_params = {"type": spec.head.type, "d": spec.head.d, "h": spec.head.h}
    if spec.head.acrossFlats is not None:
        head_params["acrossFlats"] = spec.head.acrossFlats
    attach_z, sign = shaft_axis_for_head(head_params, spec.shaft.d_minor / 2.0)

    # Thread regions are [0,10] and [15,25] from attach point; markers span [0,25].
    span_min = attach_z + sign * 0.0
    span_max = attach_z + sign * 25.0
    expected_zmin = min(span_min, span_max)
    expected_zmax = max(span_min, span_max)

    assert bb.zmin == pytest.approx(expected_zmin, abs=0.1)
    assert bb.zmax == pytest.approx(expected_zmax, abs=0.1)


def test_make_screw_from_spec_valid_solid():
    spec = ScrewSpec(
        head=HeadSpec(type="pan", d=8.0, h=4.0),
        drive=DriveSpec(type="hex", size=3),
        shaft=ShaftSpec(d_minor=4.0, L=30.0, tip_len=4.0),
        regions=[SmoothRegionSpec(length=2.0), ThreadRegionSpec(length=20.0, pitch=1.0), SmoothRegionSpec(length=8.0)],
    )
    screw = make_screw_from_spec(spec, include_thread_markers=True)
    assert screw.val().isValid()
    assert screw.val().Volume() > 0


def test_multiple_thread_regions_not_supported_yet():
    with pytest.raises(NotImplementedError, match="only one ThreadRegionSpec"):
        make_screw_from_spec(_base_spec("pan"), include_thread_markers=True)

