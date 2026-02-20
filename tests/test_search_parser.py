from __future__ import annotations

import pytest

from screwgen.search_parser import parse_query, screw_spec_from_query
from screwgen.spec import SmoothRegionSpec, ThreadRegionSpec


def test_parse_query_extracts_labeled_dimensions():
    q = (
        "pan screw head diameter 8 head height 4 "
        "shank diameter 4 root diameter 3 length 25 tip length 3 "
        "pitch 1 thread length 20"
    )
    parsed = parse_query(q)
    assert parsed.head_type == "pan"
    assert parsed.head_d == 8.0
    assert parsed.head_h == 4.0
    assert parsed.shank_d == 4.0
    assert parsed.root_d == 3.0
    assert parsed.length == 25.0
    assert parsed.tip_len == 3.0
    assert parsed.pitch == 1.0
    assert parsed.thread_length == 20.0


def test_screw_spec_requires_missing_dimensions_when_non_interactive():
    q = "pan head diameter 8 shank diameter 4 root diameter 3"
    with pytest.raises(ValueError, match="Missing required dimensions"):
        screw_spec_from_query(q)


def test_screw_spec_builds_thread_regions_from_query():
    q = (
        "flat head diameter 8 head height 4 "
        "shank diameter 4 root diameter 3 length 25 tip length 3 "
        "pitch 1 thread start 2 thread length 20"
    )
    spec = screw_spec_from_query(q)
    assert spec.head.type == "flat"
    assert spec.shaft.d_minor == 3.0
    assert len(spec.regions) == 3
    assert isinstance(spec.regions[0], SmoothRegionSpec)
    assert isinstance(spec.regions[1], ThreadRegionSpec)
    assert isinstance(spec.regions[2], SmoothRegionSpec)
    assert spec.regions[1].major_d == 4.0


def test_unrealistic_root_ratio_gets_suggested_value_when_user_accepts():
    q = (
        "pan head diameter 8 head height 4 shank diameter 4 root diameter 3.95 "
        "length 20 tip length 2 pitch 1 thread length 16"
    )
    answers = iter(["", "n"])

    def prompt(_: str) -> str:
        return next(answers)

    spec = screw_spec_from_query(q, prompt=prompt)
    assert spec.shaft.d_minor < 3.95

