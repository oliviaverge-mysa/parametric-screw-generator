"""Shaft generator (core cylinder + pointed tip), without threads."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import cadquery as cq

from .heads import head_shaft_attach_z


@dataclass(frozen=True)
class ShaftParams:
    d_minor: float
    L: float
    tip_len: float
    tip_style: str = "pointed"
    tip_angle_deg: Optional[float] = 60.0
    fillet_r: float = 0.0
    eps: float = 0.0


def _validate(p: ShaftParams) -> None:
    if p.d_minor <= 0:
        raise ValueError(f"d_minor must be > 0, got {p.d_minor!r}")
    if p.L <= 0:
        raise ValueError(f"L must be > 0, got {p.L!r}")
    if p.tip_style not in {"pointed", "flat", "flat_chamfer"}:
        raise ValueError(f"tip_style must be 'pointed', 'flat', or 'flat_chamfer', got {p.tip_style!r}")
    if p.tip_style == "pointed":
        if p.tip_len <= 0:
            raise ValueError(f"tip_len must be > 0 for pointed tip, got {p.tip_len!r}")
        if p.tip_len >= p.L:
            raise ValueError(f"tip_len must be < L, got tip_len={p.tip_len!r}, L={p.L!r}")
    else:
        if p.tip_len < 0:
            raise ValueError(f"tip_len must be >= 0 for flat_chamfer, got {p.tip_len!r}")
        if p.tip_len >= p.L:
            raise ValueError(f"tip_len must be < L, got tip_len={p.tip_len!r}, L={p.L!r}")
    if p.tip_angle_deg is not None and not (20.0 <= p.tip_angle_deg <= 120.0):
        raise ValueError(f"tip_angle_deg must be in [20, 120] when provided, got {p.tip_angle_deg!r}")
    if p.fillet_r < 0:
        raise ValueError(f"fillet_r must be >= 0, got {p.fillet_r!r}")
    if p.eps < 0:
        raise ValueError(f"eps must be >= 0, got {p.eps!r}")


def make_shaft(p: ShaftParams) -> cq.Workplane:
    _validate(p)
    r = p.d_minor / 2.0
    if p.tip_style in {"flat", "flat_chamfer"}:
        # Bolt baseline: always start from a true cylinder and keep end flat unless
        # an explicit chamfer style is requested.
        shaft = cq.Workplane("XY").circle(r).extrude(-p.L)
        chamfer = min(max(0.0, p.tip_len), r * 0.3) if p.tip_style == "flat_chamfer" else 0.0
        if chamfer > 0:
            try:
                shaft = shaft.faces("<Z").edges("%Circle").chamfer(chamfer)
            except Exception:
                pass
    else:
        z_shoulder = -(p.L - p.tip_len)
        z_tip = -p.L
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
        max_fillet = min(p.fillet_r, r * 0.49, p.tip_len * 0.49)
        if max_fillet > 0:
            shaft = shaft.edges("|X and <Z").fillet(max_fillet)
    return shaft


def resolve_shaft_attach_z(head_params, shaft_radius: float) -> float:
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
    z = h * (r_shaft - r0) / (r1 - r0)
    return max(0.0, min(h, z))


def smooth_head_shaft_junction(screw: cq.Workplane, attach_z: float, shaft_radius: float) -> cq.Workplane:
    d_minor = 2.0 * shaft_radius
    fillet_r = min(0.2, 0.08 * d_minor)
    tol_z = 0.25
    tol_r = max(0.35 * d_minor, 0.3)

    def _is_junction_edge(e) -> bool:
        c = e.Center()
        r_xy = math.hypot(c.x, c.y)
        return abs(c.z - attach_z) <= tol_z and abs(r_xy - shaft_radius) <= tol_r

    selected = screw.edges().filter(_is_junction_edge)
    if len(selected.vals()) == 0:
        return screw
    try:
        return selected.fillet(fillet_r)
    except Exception:
        try:
            return selected.chamfer(min(0.25, 0.1 * d_minor))
        except Exception:
            return screw


def attach_shaft_to_head(head: cq.Workplane, head_params, shaft: cq.Workplane) -> cq.Workplane:
    shaft_bb = shaft.val().BoundingBox()
    shaft_r = max(shaft_bb.xmax - shaft_bb.xmin, shaft_bb.ymax - shaft_bb.ymin) / 2.0
    overlap = 0.05

    attach_z = resolve_shaft_attach_z(head_params, shaft_r)
    aligned_shaft = shaft
    direction = -1.0
    if head_params["type"] == "flat":
        aligned_shaft = aligned_shaft.rotate((0, 0, 0), (1, 0, 0), 180)
        direction = +1.0
    aligned_shaft = aligned_shaft.translate((0, 0, attach_z - direction * overlap))
    screw = head.union(aligned_shaft, clean=True)
    return smooth_head_shaft_junction(screw, attach_z, shaft_r)

