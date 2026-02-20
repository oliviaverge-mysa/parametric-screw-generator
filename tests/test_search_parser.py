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


def test_parse_query_extracts_drive_type():
    parsed = parse_query("pan head diameter 8 head height 4 shank diameter 4 root diameter 3 length 25 tip 3 torx drive")
    assert parsed.drive_type == "torx"
    assert parsed.drive_size == 6


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


def test_screw_spec_infers_pitch_and_thread_height_when_thread_intent_present():
    q = "pan threaded screw head diameter 8 head height 4 shank diameter 4 root diameter 3 length 25 tip 3 thread length 20"
    spec = screw_spec_from_query(q)
    assert isinstance(spec.regions[0], ThreadRegionSpec)
    assert spec.regions[0].pitch > 0
    assert spec.regions[0].thread_height is not None
    assert spec.regions[0].thread_height > 0


def test_screw_spec_sets_drive_when_requested():
    q = "pan torx drive head diameter 8 head height 4 shank diameter 4 root diameter 3 length 25 tip 3"
    spec = screw_spec_from_query(q)
    assert spec.drive is not None
    assert spec.drive.type == "torx"
    assert spec.drive.size == 6


def test_parser_handles_common_typos_and_infers_defaults():
    q = "16mm lenght, flat head, 12mm thread, 5mm head diamter"
    spec = screw_spec_from_query(q)
    assert spec.head.type == "flat"
    assert spec.head.d == 5.0
    assert spec.head.h > 0
    assert spec.shaft.L == 16.0
    assert spec.shaft.tip_len > 0
    assert isinstance(spec.regions[0], ThreadRegionSpec)


def test_unrealistic_root_ratio_gets_suggested_value_when_user_accepts():
    q = (
        "pan head diameter 8 head height 4 shank diameter 4 root diameter 3.95 "
        "length 20 tip length 2 pitch 1 thread length 16 thread height 0.5"
    )
    answers = iter(["", "n"])

    def prompt(_: str) -> str:
        return next(answers)

    spec = screw_spec_from_query(q, prompt=prompt)
    assert spec.shaft.d_minor < 3.95

