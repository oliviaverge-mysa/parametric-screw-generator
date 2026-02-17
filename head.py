"""
Parametric screw-head generator.

Supported head types: flat, pan, button, hex.

Coordinate convention:
  - Head centered on Z axis.
  - Underside at Z = 0.
  - Head occupies Z in [0, h].
"""

from __future__ import annotations

import math
from typing import Literal, Optional, TypedDict

import cadquery as cq

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

HeadType = Literal["flat", "pan", "button", "hex"]


class HeadParams(TypedDict, total=False):
    type: HeadType
    d: float
    h: float
    acrossFlats: Optional[float]  # hex only


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_TYPES: set[HeadType] = {"flat", "pan", "button", "hex"}


def _validate(params: HeadParams) -> None:
    """Raise *ValueError* for any invalid parameter combination."""
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


# ---------------------------------------------------------------------------
# Head builders (private)
# ---------------------------------------------------------------------------

def _flat_top_d(d: float) -> float:
    """Compute the top-land diameter for a flat (countersunk) head.

    Returns a small but non-zero diameter so the top face is a real circular
    area rather than a degenerate point.  This is deterministic and depends
    only on *d*.
    """
    return max(0.05 * d, 0.2)  # mm


def _make_flat(d: float, h: float) -> cq.Workplane:
    """Countersunk conical frustum: base diameter *d* at Z=0, small flat
    circular land at Z=h.

    top_d = max(0.05 * d, 0.2) — top land added for boolean robustness;
    visually negligible.
    """
    top_d = _flat_top_d(d)
    if top_d >= d:
        raise ValueError(
            f"Computed top_d ({top_d}) must be < d ({d}); "
            "increase d or check parameters."
        )
    r_base = d / 2.0
    r_top = top_d / 2.0
    # Build explicitly from underside (Z=0, large) to tool side (Z=h, small)
    # to enforce the global convention: head occupies Z in [0, h].
    solid = (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(r_base, 0)
        .lineTo(r_top, h)
        .lineTo(0, h)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )
    return solid


def _make_domed(d: float, h: float, r_factor_d: float, r_factor_h: float) -> cq.Workplane:
    """Build a cylinder + spherical-cap head (shared logic for pan & button).

    Parameters
    ----------
    d : head diameter
    h : total head height
    r_factor_d, r_factor_h :
        dome radius = min(d * r_factor_d, h * r_factor_h)
    """
    r_head = d / 2.0
    r_dome = min(d * r_factor_d, h * r_factor_h)
    h_cyl = h - r_dome

    # Build the spherical cap as a solid of revolution.
    # The cap is a circular arc from the cylinder rim up to the apex.
    #
    # Sphere center is at (0, 0, h - r_dome) = (0, 0, h_cyl).
    # At the equator (Z = h_cyl) the sphere has radius r_dome, but we need
    # the cap edge to match the cylinder radius r_head.
    #
    # We'll revolve a 2-D profile that contains:
    #   1) a rectangle for the cylinder part (from Z=0 to Z=h_cyl, width = r_head)
    #   2) an arc for the dome (from (r_head, h_cyl) up to (0, h))
    #
    # The arc is part of a circle whose center is on the Z axis at some Zc
    # such that the circle passes through (r_head, h_cyl) and (0, h).
    #
    # Given:  R^2 = r_head^2 + (h_cyl - Zc)^2  ... (point on rim)
    #         R^2 = Zc_offset^2                 where Zc_offset = h - Zc  ... (apex)
    # =>  (h - Zc)^2 = r_head^2 + (h_cyl - Zc)^2
    # Let u = h - Zc,  v = h_cyl - Zc = u - r_dome
    # u^2 = r_head^2 + (u - r_dome)^2
    # u^2 = r_head^2 + u^2 - 2*u*r_dome + r_dome^2
    # 0   = r_head^2 - 2*u*r_dome + r_dome^2
    # u   = (r_head^2 + r_dome^2) / (2 * r_dome)
    # Zc  = h - u
    # R   = u  (distance from center to apex on axis)

    u = (r_head ** 2 + r_dome ** 2) / (2.0 * r_dome)
    zc = h - u  # sphere centre Z
    R = u        # sphere radius

    # Build 2-D half-profile in the XZ plane (X >= 0), then revolve 360°.
    # Profile points (going counter-clockwise):
    #   A = (0, 0)          bottom-centre
    #   B = (r_head, 0)     bottom-rim
    #   C = (r_head, h_cyl) top of cylinder / start of arc
    #   arc to D = (0, h)   apex
    #   back to A

    # Use CadQuery sketch on the XZ plane, revolve around Z.
    # We'll build a wire in the XZ half-plane and revolve it.

    profile = (
        cq.Workplane("XZ")
        .moveTo(0, 0)
        .lineTo(r_head, 0)
        .lineTo(r_head, h_cyl)
        .threePointArc((r_head / 2.0, h - (R - math.sqrt(R ** 2 - (r_head / 2.0) ** 2 + 1e-15))), (0, h))
        .close()
    )

    # Midpoint of arc: at X = r_head/2
    # Z_mid = zc + sqrt(R^2 - (r_head/2)^2)

    solid = profile.revolve(360, (0, 0, 0), (0, 1, 0))
    return solid


def _make_pan(d: float, h: float) -> cq.Workplane:
    """Pan head: cylinder + shallow spherical cap.  r = min(d*0.25, h*0.5)."""
    return _make_domed(d, h, 0.25, 0.5)


def _make_button(d: float, h: float) -> cq.Workplane:
    """Button head: cylinder + pronounced dome.  r = min(d*0.4, h*0.8)."""
    return _make_domed(d, h, 0.4, 0.8)


def _make_hex(d: float, h: float, across_flats: float) -> cq.Workplane:
    """Hexagonal prism from Z=0 to Z=h.

    One pair of flats is parallel to the X axis.
    The vertex (circumscribed) radius = acrossFlats / (2 * cos(30°)).
    """
    af = across_flats
    # Vertex radius from across-flats
    r_vertex = af / (2.0 * math.cos(math.radians(30)))

    # Build hexagon vertices with a flat parallel to X.
    # A regular hexagon with a flat on top/bottom (parallel to X) has vertices
    # at angles 30° + k*60° for k=0..5 when measured from the +X axis.
    # That places flats at 0° and 180° (parallel to X).
    pts: list[tuple[float, float]] = []
    for k in range(6):
        angle = math.radians(30 + k * 60)
        pts.append((r_vertex * math.cos(angle), r_vertex * math.sin(angle)))

    solid = (
        cq.Workplane("XY")
        .polyline(pts)
        .close()
        .extrude(h)
    )
    return solid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_head(params: HeadParams) -> cq.Workplane:
    """Create a screw-head solid from *params*.

    Returns a CadQuery Workplane whose val() is the resulting solid.
    """
    _validate(params)

    head_type: HeadType = params["type"]
    d: float = float(params["d"])
    h: float = float(params["h"])

    if head_type == "flat":
        return _make_flat(d, h)

    if head_type == "pan":
        return _make_pan(d, h)

    if head_type == "button":
        return _make_button(d, h)

    if head_type == "hex":
        af = float(params.get("acrossFlats") or d)
        return _make_hex(d, h, af)

    # Unreachable after validation, but kept for safety.
    raise ValueError(f"Unhandled head type: {head_type!r}")


def head_tool_z(params: HeadParams) -> float:
    """Return the drive/tool face Z for the given head params.

    Conventions:
      - flat head: tool side is the large flat face at Z=0
      - all other heads: tool side is at Z=h
    """
    _validate(params)
    if params["type"] == "flat":
        return 0.0
    return float(params["h"])


def head_shaft_attach_z(params: HeadParams) -> float:
    """Return the head-plane Z where the shaft must attach.

    Conventions:
      - flat head: attach on countersunk/cone side at Z=h
      - pan/button/hex: attach on underside at Z=0
    """
    _validate(params)
    if params["type"] == "flat":
        return float(params["h"])
    return 0.0
