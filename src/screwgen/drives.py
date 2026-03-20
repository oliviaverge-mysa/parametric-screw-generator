"""
Parametric drive-recess generator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal

import cadquery as cq

DriveType = Literal["hex", "phillips", "torx", "square"]
DriveSize = Literal[3, 4, 5, 6]
DriveFit = Literal["nominal", "scale_to_head", "max_that_fits"]

DRIVE_DIMS: dict[tuple[DriveType, DriveSize], dict] = {
    ("hex", 3): {"across_flats": 3.0},
    ("phillips", 4): {"slot_w": 1.6, "slot_l": 5.5},
    ("square", 5): {"across_flats": 2.6},
    ("torx", 6): {"r_outer": 3.0, "r_inner": 2.2, "r_fillet": 0.35, "segments": 48},
}

CONFIG: dict[str, float] = {
    "hex_opening_fraction": 0.35,
    "phillips_opening_fraction": 0.45,
    "square_opening_fraction": 0.35,
    "torx_opening_fraction": 0.38,
    "min_wall_abs": 0.6,
    "min_wall_fraction": 0.12,
    "cone_cover_margin": 0.2,
    "cone_tip_radius": 0.05,
}

_VALID_COMBOS: dict[DriveType, DriveSize] = {"hex": 3, "phillips": 4, "square": 5, "torx": 6}


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
    slotted: bool = False


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


def _square_profile(af: float) -> cq.Workplane:
    return cq.Workplane("XY").rect(af, af)


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
    nominal_af = DRIVE_DIMS[("square", 5)]["across_flats"] + 2.0 * p.clearance
    af = nominal_af * _opening_scale(p, nominal_af)
    opening_radius = af / math.sqrt(2.0)
    return _build_dished_cut(p, lambda: _square_profile(af), opening_radius)


_SLOT_ROTATION_DEG: dict[DriveType, float] = {
    "phillips": 0.0,
    "square": 45.0,
    "hex": 0.0,
    "torx": 0.0,
}


def _drive_slot_width(p: DriveParams) -> float:
    """Compute slot width that matches the drive recess proportions."""
    head_d = p.head_d if p.head_d is not None else 8.0
    min_w = max(0.4, head_d * 0.10)
    if p.type == "phillips":
        nominal_slot_w = DRIVE_DIMS[("phillips", 4)]["slot_w"] + 2.0 * p.clearance
        nominal_slot_l = DRIVE_DIMS[("phillips", 4)]["slot_l"] + 2.0 * p.clearance
        return max(min_w, nominal_slot_w * _opening_scale(p, nominal_slot_l))
    if p.type == "square":
        nominal_af = DRIVE_DIMS[("square", 5)]["across_flats"] + 2.0 * p.clearance
        af = nominal_af * _opening_scale(p, nominal_af)
        return max(min_w, af * 0.38)
    if p.type == "hex":
        nominal_af = DRIVE_DIMS[("hex", 3)]["across_flats"] + 2.0 * p.clearance
        af = nominal_af * _opening_scale(p, nominal_af)
        return max(min_w, af * 0.35)
    if p.type == "torx":
        nominal_r_outer = DRIVE_DIMS[("torx", 6)]["r_outer"] + p.clearance
        scale = _opening_scale(p, 2.0 * nominal_r_outer)
        r_inner = (DRIVE_DIMS[("torx", 6)]["r_inner"] + p.clearance) * scale
        return max(min_w, r_inner * 0.45)
    return min_w


def _make_slot_cut(p: DriveParams) -> cq.Workplane:
    """Build a straight slot cut spanning the full head diameter.

    Slot depth is 75% of the drive depth so it doesn't dominate the head.
    """
    head_d = p.head_d if p.head_d is not None else 8.0
    slot_length = head_d * 1.05
    slot_width = _drive_slot_width(p)
    slot_depth = p.depth * 0.75
    z_bottom = p.topZ - slot_depth - p.eps
    h_total = slot_depth + 2.0 * p.eps
    slot = (
        cq.Workplane("XY")
        .rect(slot_length, slot_width)
        .extrude(h_total)
        .translate((0, 0, z_bottom))
    )
    rotation = _SLOT_ROTATION_DEG.get(p.type, 0.0)
    if rotation != 0.0:
        slot = slot.rotate((0, 0, 0), (0, 0, 1), rotation)
    return slot


def make_drive_cut(p: DriveParams) -> cq.Workplane:
    _validate(p)
    if p.type == "hex":
        cut = _make_hex_cut(p)
    elif p.type == "phillips":
        cut = _make_phillips_cut(p)
    elif p.type == "square":
        cut = _make_square_cut(p)
    elif p.type == "torx":
        cut = _make_torx_cut(p)
    else:
        raise ValueError(f"Unhandled drive type: {p.type!r}")
    if p.slotted:
        slot = _make_slot_cut(p)
        cut = cut.union(slot, clean=True)
    return cut

