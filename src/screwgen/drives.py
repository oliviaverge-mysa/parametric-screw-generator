"""
Parametric drive-recess generator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal

import cadquery as cq

DriveType = Literal["hex", "phillips", "torx", "square"]
DriveSize = Literal[3, 4, 6]
DriveFit = Literal["nominal", "scale_to_head", "max_that_fits"]

DRIVE_DIMS: dict[tuple[DriveType, DriveSize], dict] = {
    ("hex", 3): {"across_flats": 3.0},
    ("phillips", 4): {"slot_w": 1.6, "slot_l": 5.5},
    ("torx", 6): {"r_outer": 3.0, "r_inner": 2.2, "r_fillet": 0.35, "segments": 48},
    ("square", 4): {"side": 2.4},
}

CONFIG: dict[str, float] = {
    "hex_opening_fraction": 0.35,
    "phillips_opening_fraction": 0.45,
    "torx_opening_fraction": 0.38,
    "square_opening_fraction": 0.34,
    "min_wall_abs": 0.6,
    "min_wall_fraction": 0.12,
    "cone_cover_margin": 0.2,
    "cone_tip_radius": 0.05,
}

_VALID_COMBOS: dict[DriveType, DriveSize] = {"hex": 3, "phillips": 4, "torx": 6, "square": 4}


@dataclass(frozen=True)
class DriveParams:
    type: DriveType
    size: DriveSize
    depth: float
    topZ: float
    clearance: float = 0.05
    eps: float = 0.05
    fit: DriveFit = "nominal"
    head_d: float | None = None
    min_wall: float | None = None


def _validate(p: DriveParams) -> None:
    if p.type not in _VALID_COMBOS:
        raise ValueError(f"Unknown drive type {p.type!r}. Must be one of {sorted(_VALID_COMBOS)}.")
    expected_size = _VALID_COMBOS[p.type]
    if p.size != expected_size:
        raise ValueError(f"Drive type {p.type!r} requires size={expected_size}, got size={p.size}.")
    if p.depth <= 0:
        raise ValueError(f"depth must be > 0, got {p.depth!r}")
    if p.topZ <= 0:
        raise ValueError(f"topZ must be > 0, got {p.topZ!r}")
    if p.fit not in ("nominal", "scale_to_head", "max_that_fits"):
        raise ValueError(
            f"fit must be one of ('nominal','scale_to_head','max_that_fits'), got {p.fit!r}"
        )
    if p.head_d is not None and p.head_d <= 0:
        raise ValueError(f"head_d must be > 0 when provided, got {p.head_d!r}")
    if p.min_wall is not None and p.min_wall <= 0:
        raise ValueError(f"min_wall must be > 0 when provided, got {p.min_wall!r}")
    if p.fit in ("scale_to_head", "max_that_fits") and (p.head_d is None or p.head_d <= 0):
        raise ValueError(f"fit={p.fit!r} requires head_d > 0 so opening can be scaled/clamped.")


def _min_wall_for_head(p: DriveParams) -> float:
    if p.head_d is None:
        return CONFIG["min_wall_abs"]
    return p.min_wall if p.min_wall is not None else max(
        CONFIG["min_wall_abs"], CONFIG["min_wall_fraction"] * p.head_d
    )


def _max_opening_radius(p: DriveParams) -> float:
    if p.head_d is None:
        return float("inf")
    return max(p.head_d / 2.0 - _min_wall_for_head(p), 0.1)


def _target_opening_diameter(p: DriveParams) -> float:
    if p.head_d is None:
        raise ValueError(f"fit={p.fit!r} requires head_d > 0.")
    if p.type == "hex":
        target = CONFIG["hex_opening_fraction"] * p.head_d
    elif p.type == "phillips":
        target = CONFIG["phillips_opening_fraction"] * p.head_d
    elif p.type == "square":
        target = CONFIG["square_opening_fraction"] * p.head_d
    else:
        target = CONFIG["torx_opening_fraction"] * p.head_d
    return min(target, 2.0 * _max_opening_radius(p))


def _opening_scale(p: DriveParams, nominal_opening_diameter: float) -> float:
    if p.fit == "nominal":
        return 1.0
    if p.fit == "scale_to_head":
        return _target_opening_diameter(p) / nominal_opening_diameter
    return (2.0 * _max_opening_radius(p)) / nominal_opening_diameter


def _z_span_total(p: DriveParams) -> tuple[float, float]:
    return p.topZ - p.depth - p.eps, p.depth + 2.0 * p.eps


def _hex_profile(af: float) -> cq.Workplane:
    r_vertex = af / (2.0 * math.cos(math.pi / 6))
    pts = []
    for k in range(6):
        angle = math.radians(30 + k * 60)
        pts.append((r_vertex * math.cos(angle), r_vertex * math.sin(angle)))
    return cq.Workplane("XY").polyline(pts).close()


def _phillips_profile(slot_l: float, slot_w: float) -> cq.Workplane:
    sketch = cq.Sketch().rect(slot_l, slot_w).rect(slot_w, slot_l).circle(slot_w * 0.6)
    return cq.Workplane("XY").placeSketch(sketch)


def _torx_profile(r_outer: float, r_inner: float, segments: int) -> cq.Workplane:
    r_mean = (r_outer + r_inner) / 2.0
    r_amp = (r_outer - r_inner) / 2.0
    pts = []
    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        r = r_mean + r_amp * math.cos(6.0 * theta)
        pts.append((r * math.cos(theta), r * math.sin(theta)))
    return cq.Workplane("XY").polyline(pts).close()


def _square_profile(side: float) -> cq.Workplane:
    s = side / 2.0
    pts = [(-s, -s), (s, -s), (s, s), (-s, s)]
    return cq.Workplane("XY").polyline(pts).close()


def _build_dished_cut(
    p: DriveParams, profile_factory: Callable[[], cq.Workplane], opening_radius: float
) -> cq.Workplane:
    z_bottom_total, h_total = _z_span_total(p)
    prism = profile_factory().extrude(h_total).translate((0, 0, z_bottom_total))
    r_edge = opening_radius + CONFIG["cone_cover_margin"]
    r_tip = CONFIG["cone_tip_radius"]
    cone = (
        cq.Workplane("XY")
        .workplane(offset=z_bottom_total)
        .circle(r_tip)
        .workplane(offset=h_total)
        .circle(r_edge)
        .loft()
    )
    return prism.intersect(cone)


def _make_hex_cut(p: DriveParams) -> cq.Workplane:
    nominal_af = DRIVE_DIMS[("hex", 3)]["across_flats"] + 2.0 * p.clearance
    af = nominal_af * _opening_scale(p, nominal_af)
    opening_radius = af / (2.0 * math.cos(math.pi / 6))
    return _build_dished_cut(p, lambda: _hex_profile(af), opening_radius)


def _make_phillips_cut(p: DriveParams) -> cq.Workplane:
    nominal_slot_l = DRIVE_DIMS[("phillips", 4)]["slot_l"] + 2.0 * p.clearance
    nominal_slot_w = DRIVE_DIMS[("phillips", 4)]["slot_w"] + 2.0 * p.clearance
    scale = _opening_scale(p, nominal_slot_l)
    slot_l = nominal_slot_l * scale
    slot_w = nominal_slot_w * scale
    return _build_dished_cut(p, lambda: _phillips_profile(slot_l, slot_w), slot_l / 2.0)


def _make_torx_cut(p: DriveParams) -> cq.Workplane:
    nominal_r_outer = DRIVE_DIMS[("torx", 6)]["r_outer"] + p.clearance
    scale = _opening_scale(p, 2.0 * nominal_r_outer)
    r_outer = nominal_r_outer * scale
    r_inner = (DRIVE_DIMS[("torx", 6)]["r_inner"] + p.clearance) * scale
    segments = DRIVE_DIMS[("torx", 6)]["segments"]
    return _build_dished_cut(p, lambda: _torx_profile(r_outer, r_inner, segments), r_outer)


def _make_square_cut(p: DriveParams) -> cq.Workplane:
    nominal_side = DRIVE_DIMS[("square", 4)]["side"] + 2.0 * p.clearance
    scale = _opening_scale(p, nominal_side * math.sqrt(2.0))
    side = nominal_side * scale
    opening_radius = (side * math.sqrt(2.0)) / 2.0
    return _build_dished_cut(p, lambda: _square_profile(side), opening_radius)


def make_drive_cut(p: DriveParams) -> cq.Workplane:
    _validate(p)
    if p.type == "hex":
        return _make_hex_cut(p)
    if p.type == "phillips":
        return _make_phillips_cut(p)
    if p.type == "torx":
        return _make_torx_cut(p)
    if p.type == "square":
        return _make_square_cut(p)
    raise ValueError(f"Unhandled drive type: {p.type!r}")

