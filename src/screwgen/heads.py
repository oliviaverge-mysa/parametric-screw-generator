"""
Parametric screw-head generator.

Supported head types: flat, pan, button, hex.
"""

from __future__ import annotations

import math
from typing import Literal, Optional, TypedDict

import cadquery as cq

HeadType = Literal["flat", "pan", "button", "hex"]


class HeadParams(TypedDict, total=False):
    type: HeadType
    d: float
    h: float
    acrossFlats: Optional[float]
    flatTopD: float
    domeRadius: float


_VALID_TYPES: set[HeadType] = {"flat", "pan", "button", "hex"}


def _validate(params: HeadParams) -> None:
    head_type = params.get("type")
    if head_type not in _VALID_TYPES:
        raise ValueError(
            f"Unknown head type {head_type!r}. Must be one of {sorted(_VALID_TYPES)}."
        )
    d = params.get("d")
    if d is None or d <= 0:
        raise ValueError(f"d must be > 0, got {d!r}")
    h = params.get("h")
    if h is None or h <= 0:
        raise ValueError(f"h must be > 0, got {h!r}")
    af = params.get("acrossFlats")
    if af is not None and af <= 0:
        raise ValueError(f"acrossFlats must be > 0 when provided, got {af!r}")
    flat_top_d = params.get("flatTopD")
    if flat_top_d is not None and flat_top_d <= 0:
        raise ValueError(f"flatTopD must be > 0 when provided, got {flat_top_d!r}")
    dome_radius = params.get("domeRadius")
    if dome_radius is not None and dome_radius <= 0:
        raise ValueError(f"domeRadius must be > 0 when provided, got {dome_radius!r}")


def _flat_top_d(d: float) -> float:
    return max(0.05 * d, 0.2)


def _make_flat(d: float, h: float, top_d: float) -> cq.Workplane:
    if top_d >= d:
        raise ValueError(
            f"Computed top_d ({top_d}) must be < d ({d}); increase d or check parameters."
        )
    r_base = d / 2.0
    r_top = top_d / 2.0
    return (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(r_base, 0)
        .lineTo(r_top, h)
        .lineTo(0, h)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )


def _make_domed(
    d: float,
    h: float,
    r_factor_d: float,
    r_factor_h: float,
    dome_radius: float | None = None,
) -> cq.Workplane:
    r_head = d / 2.0
    r_dome = dome_radius if dome_radius is not None else min(d * r_factor_d, h * r_factor_h)
    if r_dome >= h:
        raise ValueError(f"domeRadius must be < h, got domeRadius={r_dome!r}, h={h!r}")
    h_cyl = h - r_dome
    u = (r_head**2 + r_dome**2) / (2.0 * r_dome)
    R = u
    profile = (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(r_head, 0)
        .lineTo(r_head, h_cyl)
        .threePointArc(
            (r_head / 2.0, h - (R - math.sqrt(R**2 - (r_head / 2.0) ** 2 + 1e-15))),
            (0, h),
        )
        .close()
    )
    return profile.revolve(360, (0, 0, 0), (0, 1, 0))


def _make_pan(d: float, h: float, dome_radius: float | None = None) -> cq.Workplane:
    return _make_domed(d, h, 0.25, 0.5, dome_radius=dome_radius)


def _make_button(d: float, h: float, dome_radius: float | None = None) -> cq.Workplane:
    return _make_domed(d, h, 0.4, 0.8, dome_radius=dome_radius)


def _make_hex(d: float, h: float, across_flats: float) -> cq.Workplane:
    r_vertex = across_flats / (2.0 * math.cos(math.radians(30)))
    pts: list[tuple[float, float]] = []
    for k in range(6):
        angle = math.radians(30 + k * 60)
        pts.append((r_vertex * math.cos(angle), r_vertex * math.sin(angle)))
    return cq.Workplane("XY").polyline(pts).close().extrude(h)


def make_head(params: HeadParams) -> cq.Workplane:
    _validate(params)
    head_type: HeadType = params["type"]
    d = float(params["d"])
    h = float(params["h"])
    flat_top_d = params.get("flatTopD")
    dome_radius = params.get("domeRadius")
    if head_type == "flat":
        return _make_flat(d, h, float(flat_top_d) if flat_top_d is not None else _flat_top_d(d))
    if head_type == "pan":
        return _make_pan(d, h, float(dome_radius) if dome_radius is not None else None)
    if head_type == "button":
        return _make_button(d, h, float(dome_radius) if dome_radius is not None else None)
    if head_type == "hex":
        af_raw = params.get("acrossFlats")
        if af_raw is None:
            raise ValueError("acrossFlats must be provided for hex heads.")
        af = float(af_raw)
        return _make_hex(d, h, af)
    raise ValueError(f"Unhandled head type: {head_type!r}")


def head_tool_z(params: HeadParams) -> float:
    _validate(params)
    if params["type"] == "flat":
        return 0.0
    return float(params["h"])


def head_shaft_attach_z(params: HeadParams) -> float:
    _validate(params)
    if params["type"] == "flat":
        return float(params["h"])
    return 0.0

