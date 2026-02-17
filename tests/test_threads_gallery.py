from __future__ import annotations

import cadquery as cq
import pytest

from screwgen.assembly import apply_drive_to_head
from screwgen.drives import DriveParams
from screwgen.heads import head_tool_z, make_head
from screwgen.preview import preview_threads_gallery as ptg
from screwgen.preview.preview_threads_gallery import BASE_SHAFT, build_thread_gallery_compound, build_thread_gallery_solids, export_thread_gallery
from screwgen.shaft import ShaftParams, make_shaft
from screwgen.threads import ThreadParams, apply_external_thread


def test_thread_gallery_smoke_count_and_valid(tmp_path, monkeypatch):
    def _stub_compose_screw(head_type: str, drive_type: str, drive_size: int, pitch: float):
        _ = (head_type, drive_type, drive_size, pitch)
        return cq.Workplane("XY").circle(2.0).extrude(8.0)

    monkeypatch.setattr(ptg, "_compose_screw", _stub_compose_screw)
    solids = build_thread_gallery_solids()
    assert len(solids) == 36
    comp = build_thread_gallery_compound()
    assert comp.val().isValid()
    gallery_path, section_path, count = export_thread_gallery(tmp_path)
    assert count == 36
    assert gallery_path.exists()
    assert section_path.exists()
    gallery_default, section_default, default_count = export_thread_gallery()
    assert default_count == 36
    assert "\\out\\galleries\\step\\" in str(gallery_default)
    assert "\\out\\galleries\\sectioned\\step\\" in str(section_default)


def test_sample_threaded_screw_pipeline_metrics():
    hp = {"type": "pan", "d": 8.0, "h": 4.0}
    head = make_head(hp)
    drive = DriveParams(
        type="torx",
        size=6,
        depth=min(2.0, 0.45 * hp["h"]),
        topZ=head_tool_z(hp),
        fit="scale_to_head",
        head_d=hp["d"],
    )
    driven = apply_drive_to_head(head, drive, hp)
    assert driven.val().Volume() < head.val().Volume()

    shaft = make_shaft(ShaftParams(d_minor=BASE_SHAFT.d_minor, L=BASE_SHAFT.L, tip_len=BASE_SHAFT.tip_len))
    shaft_up = shaft.rotate((0, 0, 0), (1, 0, 0), 180)
    threaded_up = apply_external_thread(
        shaft_up,
        BASE_SHAFT,
        ThreadParams(pitch=1.0, length=20.0, start_from_head=2.0, mode="cut"),
    )
    bb = threaded_up.val().BoundingBox()
    max_d = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
    assert max_d > BASE_SHAFT.d_minor
    assert threaded_up.val().isValid()

