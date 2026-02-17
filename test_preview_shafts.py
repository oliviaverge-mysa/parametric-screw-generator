"""
Minimal integration test for shaft preview library export.
"""

from __future__ import annotations

from pathlib import Path

from preview_shafts import _HEAD_ORDER, _shaft_variants, export_screw_library


def test_screw_library_export_and_count(tmp_path: Path):
    library_path, section_path, solid_count = export_screw_library(tmp_path)

    expected = len(_HEAD_ORDER) * len(_shaft_variants())
    assert solid_count == expected
    assert library_path.exists()
    assert section_path.exists()

