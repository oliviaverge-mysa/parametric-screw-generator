"""
Parametric drive-recess generator.

Returns a solid intended to be boolean-subtracted from a screw head.

Supported drive types:
  - hex      (size 3)
  - phillips (size 4)
  - torx     (size 6)

Coordinate convention:
  - Cut solid centered on Z axis (X=0, Y=0).
  - Cut spans Z in [topZ - depth - eps, topZ + eps].
  - Cut direction is along -Z.
  - Deterministic — no randomness, no global state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal

import cadquery as cq

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

DriveType = Literal["hex", "phillips", "torx"]
DriveSize = Literal[3, 4, 6]
DriveFit = Literal["nominal", "scale_to_head", "max_that_fits"]

# ---------------------------------------------------------------------------
# Dimension lookup table (nominal geometry)
# ---------------------------------------------------------------------------
# Starter values (not ISO-perfect). The goal is: looks right + boolean
# robust.  Numbers can be refined later without rewriting code.

DRIVE_DIMS: dict[tuple[DriveType, DriveSize], dict] = {
    ("hex", 3): {
        "across_flats": 3.0,
    },
    ("phillips", 4): {
        "slot_w": 1.6,
        "slot_l": 5.5,
    },
    ("torx", 6): {
        "r_outer": 3.0,
        "r_inner": 2.2,
        "r_fillet": 0.35,   # stored for future refinement; see _make_torx_cut
        "segments": 48,
    },
}

# ---------------------------------------------------------------------------
# Global tuning configuration
# ---------------------------------------------------------------------------
# Keep all sizing/depth policy constants in one place for easy tuning.

CONFIG: dict[str, float] = {
    # Opening targets vs. head diameter for auto-fit.
    "hex_opening_fraction": 0.35,       # across-flats / head_d
    "phillips_opening_fraction": 0.45,  # overall opening width / head_d
    "torx_opening_fraction": 0.45,      # outer diameter / head_d
    # Min wall around drive opening.
    "min_wall_abs": 0.6,                # mm
    "min_wall_fraction": 0.12,          # * head_d
    # Conical-depth profile inside drive footprint (prism ∩ cone).
    "cone_cover_margin": 0.2,           # mm extra radius beyond opening
    "cone_tip_radius": 0.05,            # mm tiny bottom radius for OCCT robustness
}

# Valid (type -> required size) pairings.
_VALID_COMBOS: dict[DriveType, DriveSize] = {
    "hex": 3,
    "phillips": 4,
    "torx": 6,
}

# ---------------------------------------------------------------------------
# Params dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriveParams:
    type: DriveType
    size: DriveSize
    depth: float
    topZ: float               # where the recess starts (usually head top Z = h)
    clearance: float = 0.05   # mm — grows the profile outward
    eps: float = 0.05         # mm — overlap for boolean robustness
    fit: DriveFit = "nominal"
    head_d: float | None = None
    min_wall: float | None = None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(p: DriveParams) -> None:
    """Raise *ValueError* for any invalid parameter combination."""
    if p.type not in _VALID_COMBOS:
        raise ValueError(
            f"Unknown drive type {p.type!r}. "
            f"Must be one of {sorted(_VALID_COMBOS)}."
        )
    expected_size = _VALID_COMBOS[p.type]
    if p.size != expected_size:
        raise ValueError(
            f"Drive type {p.type!r} requires size={expected_size}, "
            f"got size={p.size}."
        )
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
        raise ValueError(
            f"fit={p.fit!r} requires head_d > 0 so opening can be scaled/clamped."
        )


# ---------------------------------------------------------------------------
# Private builders
# ---------------------------------------------------------------------------


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
    else:
        target = CONFIG["torx_opening_fraction"] * p.head_d

    max_d = 2.0 * _max_opening_radius(p)
    return min(target, max_d)


def _opening_scale(p: DriveParams, nominal_opening_diameter: float) -> float:
    """Scale factor applied to nominal 2D profile dimensions."""
    if p.fit == "nominal":
        return 1.0
    if p.fit == "scale_to_head":
        return _target_opening_diameter(p) / nominal_opening_diameter
    # max_that_fits
    return (2.0 * _max_opening_radius(p)) / nominal_opening_diameter


def _z_span_total(p: DriveParams) -> tuple[float, float]:
    z_bottom_total = p.topZ - p.depth - p.eps
    h_total = p.depth + 2.0 * p.eps
    return z_bottom_total, h_total


def _hex_profile(af: float) -> cq.Workplane:
    r_vertex = af / (2.0 * math.cos(math.pi / 6))
    pts: list[tuple[float, float]] = []
    for k in range(6):
        angle = math.radians(30 + k * 60)  # flats parallel to X
        pts.append((r_vertex * math.cos(angle), r_vertex * math.sin(angle)))
    return cq.Workplane("XY").polyline(pts).close()


def _phillips_profile(slot_l: float, slot_w: float) -> cq.Workplane:
    sketch = (
        cq.Sketch()
        .rect(slot_l, slot_w)
        .rect(slot_w, slot_l)
        .circle(slot_w * 0.6)
    )
    return cq.Workplane("XY").placeSketch(sketch)


def _torx_profile(r_outer: float, r_inner: float, segments: int) -> cq.Workplane:
    r_mean = (r_outer + r_inner) / 2.0
    r_amp = (r_outer - r_inner) / 2.0
    pts: list[tuple[float, float]] = []
    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        r = r_mean + r_amp * math.cos(6.0 * theta)
        pts.append((r * math.cos(theta), r * math.sin(theta)))
    return cq.Workplane("XY").polyline(pts).close()


def _build_dished_cut(
    p: DriveParams,
    profile_factory: Callable[[], cq.Workplane],
    opening_radius: float,
) -> cq.Workplane:
    """Build conical-depth cut as footprint prism intersected with cone.

    This keeps the top opening footprint unchanged while enforcing a
    continuously sloped bottom that is deepest at the center.
    """
    z_bottom_total, h_total = _z_span_total(p)

    # A) Footprint prism spanning full recess depth envelope.
    prism = profile_factory().extrude(h_total).translate((0, 0, z_bottom_total))

    # B) Cone/frustum covering the footprint at top and collapsing toward center.
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
    dims = DRIVE_DIMS[("hex", 3)]
    nominal_af = dims["across_flats"] + 2.0 * p.clearance
    scale = _opening_scale(p, nominal_af)
    af = nominal_af * scale
    opening_radius = af / (2.0 * math.cos(math.pi / 6))
    return _build_dished_cut(p, lambda: _hex_profile(af), opening_radius)


def _make_phillips_cut(p: DriveParams) -> cq.Workplane:
    dims = DRIVE_DIMS[("phillips", 4)]
    nominal_slot_l = dims["slot_l"] + 2.0 * p.clearance
    nominal_slot_w = dims["slot_w"] + 2.0 * p.clearance
    nominal_overall = nominal_slot_l
    scale = _opening_scale(p, nominal_overall)
    slot_l = nominal_slot_l * scale
    slot_w = nominal_slot_w * scale
    opening_radius = slot_l / 2.0
    return _build_dished_cut(p, lambda: _phillips_profile(slot_l, slot_w), opening_radius)


def _make_torx_cut(p: DriveParams) -> cq.Workplane:
    dims = DRIVE_DIMS[("torx", 6)]
    nominal_r_outer = dims["r_outer"] + p.clearance
    nominal_opening_d = 2.0 * nominal_r_outer
    scale = _opening_scale(p, nominal_opening_d)
    r_outer = nominal_r_outer * scale
    r_inner = (dims["r_inner"] + p.clearance) * scale
    segments: int = dims["segments"]
    return _build_dished_cut(p, lambda: _torx_profile(r_outer, r_inner, segments), r_outer)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_drive_cut(p: DriveParams) -> cq.Workplane:
    """Return a solid meant to be subtracted from a head.

    - Centered on Z axis.
    - Spans Z in [topZ - depth - eps, topZ + eps].
    - Deterministic, no randomness.
    """
    _validate(p)

    if p.type == "hex":
        return _make_hex_cut(p)
    if p.type == "phillips":
        return _make_phillips_cut(p)
    if p.type == "torx":
        return _make_torx_cut(p)

    # Unreachable after validation, but kept for safety.
    raise ValueError(f"Unhandled drive type: {p.type!r}")
