"""
Shaft generator (core cylinder + pointed tip), without threads.

Coordinate convention:
  - Shaft is centered on the Z axis.
  - Shaft top mating plane is at Z = 0 (head underside plane).
  - Shaft extends downward along -Z to Z = -L.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import cadquery as cq

from head import head_shaft_attach_z


@dataclass(frozen=True)
class ShaftParams:
    d_minor: float
    L: float
    tip_len: float
    tip_angle_deg: Optional[float] = 60.0
    fillet_r: float = 0.0
    eps: float = 0.0


def _validate(p: ShaftParams) -> None:
    if p.d_minor <= 0:
        raise ValueError(f"d_minor must be > 0, got {p.d_minor!r}")
    if p.L <= 0:
        raise ValueError(f"L must be > 0, got {p.L!r}")
    if p.tip_len <= 0:
        raise ValueError(f"tip_len must be > 0, got {p.tip_len!r}")
    if p.tip_len >= p.L:
        raise ValueError(f"tip_len must be < L, got tip_len={p.tip_len!r}, L={p.L!r}")
    if p.tip_angle_deg is not None and not (20.0 <= p.tip_angle_deg <= 120.0):
        raise ValueError(
            f"tip_angle_deg must be in [20, 120] when provided, got {p.tip_angle_deg!r}"
        )
    if p.fillet_r < 0:
        raise ValueError(f"fillet_r must be >= 0, got {p.fillet_r!r}")
    if p.eps < 0:
        raise ValueError(f"eps must be >= 0, got {p.eps!r}")


def make_shaft(p: ShaftParams) -> cq.Workplane:
    """
    Returns a solid shaft centered on Z axis:
    - cylinder from Z=0 down to Z=-(L - tip_len)
    - conical tip from Z=-(L - tip_len) down to Z=-L, ending at a point on axis

    Deterministic rule:
    - tip_len is authoritative and always drives geometry.
    - tip_angle_deg is validated for reasonableness but informational only.
    """
    _validate(p)

    r = p.d_minor / 2.0
    z_shoulder = -(p.L - p.tip_len)
    z_tip = -p.L

    # Build one watertight profile and revolve for robustness.
    shaft = (
        cq.Workplane("XZ")
        .moveTo(0.0, 0.0)
        .lineTo(r, 0.0)
        .lineTo(r, z_shoulder)
        .lineTo(0.0, z_tip)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )

    if p.fillet_r > 0:
        # Apply small shoulder fillet if requested; limited by local geometry.
        max_fillet = min(p.fillet_r, r * 0.49, p.tip_len * 0.49)
        if max_fillet > 0:
            shaft = shaft.edges("|X and <Z").fillet(max_fillet)

    return shaft


def attach_shaft_to_head(
    head: cq.Workplane, head_params, shaft: cq.Workplane
) -> cq.Workplane:
    """
    Returns head ∪ shaft with robust union and a small smoothed junction.

    - For flat heads, shaft is flipped and attached at the cone-matching
      radius location (inside cone by a tiny overlap) so transition is seamless.
    - For other heads, shaft attaches at the underside plane with tiny overlap.
    """
    shaft_bb = shaft.val().BoundingBox()
    shaft_L = shaft_bb.zmax - shaft_bb.zmin
    shaft_r = max(shaft_bb.xmax - shaft_bb.xmin, shaft_bb.ymax - shaft_bb.ymin) / 2.0
    overlap = 0.05

    attach_z = resolve_shaft_attach_z(head_params, shaft_r)
    aligned_shaft = shaft
    direction = -1.0
    if head_params["type"] == "flat":
        aligned_shaft = aligned_shaft.rotate((0, 0, 0), (1, 0, 0), 180)
        direction = +1.0

    # top face (local Z=0) is moved slightly inside the head for robust union.
    aligned_shaft = aligned_shaft.translate((0, 0, attach_z - direction * overlap))
    screw = head.union(aligned_shaft, clean=True)
    return smooth_head_shaft_junction(screw, attach_z, shaft_r)


def resolve_shaft_attach_z(head_params, shaft_radius: float) -> float:
    """Resolve shaft attach plane for a head.

    For flat heads, compute a seamless cone match location:
      r(z) = r0 + (r1-r0)*(z/h), where r0=d/2 at z=0, r1=top_d/2 at z=h.
      Solve r(z_attach)=shaft_radius with clamped fallbacks.
    """
    if head_params["type"] != "flat":
        return float(head_shaft_attach_z(head_params))

    d = float(head_params["d"])
    h = float(head_params["h"])
    top_d = max(0.05 * d, 0.2)
    r0 = d / 2.0
    r1 = top_d / 2.0
    r_shaft = float(shaft_radius)

    if r_shaft >= r0:
        return 0.0
    if r_shaft <= r1:
        return h

    # r1 < r0 for flat heads; denominator is negative.
    z = h * (r_shaft - r0) / (r1 - r0)
    return max(0.0, min(h, z))


def smooth_head_shaft_junction(
    screw: cq.Workplane, attach_z: float, shaft_radius: float
) -> cq.Workplane:
    """Apply a tiny junction fillet/chamfer around the head↔shaft seam."""
    d_minor = 2.0 * shaft_radius
    fillet_r = min(0.2, 0.08 * d_minor)
    tol_z = 0.25
    tol_r = max(0.35 * d_minor, 0.3)

    def _is_junction_edge(e) -> bool:
        c = e.Center()
        # keep only near junction z and near shaft outer radius region
        r_xy = math.hypot(c.x, c.y)
        return abs(c.z - attach_z) <= tol_z and abs(r_xy - shaft_radius) <= tol_r

    selected = screw.edges().filter(_is_junction_edge)
    if len(selected.vals()) == 0:
        return screw

    try:
        return selected.fillet(fillet_r)
    except Exception:
        # Fallback to tiny chamfer when fillet kernel solve fails.
        try:
            return selected.chamfer(min(0.25, 0.1 * d_minor))
        except Exception:
            return screw

