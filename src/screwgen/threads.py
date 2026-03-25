"""External thread geometry: smooth-arc helical profile with tip taper.

Uses a D-shaped cross-section (circular arc + straight close) instead of
a triangle.  A triangle creates 3 sharp helical edges that all show in
the SVG wireframe ("tri-ridge").  The arc has only 2 sharp corners (both
at the root, merging into one visible line) while the crest is part of
the smooth arc surface — no edge line there.

For screws with conical tips the thread is continued in finely-scaled
segments so the teeth follow the narrowing cone smoothly to the point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace as _replace
from typing import Literal

import cadquery as cq

from .spec import ShaftSpec


@dataclass(frozen=True)
class ThreadParams:
    pitch: float
    length: float
    start_from_head: float = 0.0
    included_angle_deg: float = 60.0
    thread_height: float | None = None
    major_d: float | None = None
    handedness: Literal["RH", "LH"] = "RH"
    starts: int = 1
    mode: Literal["add", "cut"] = "add"
    clearance: float = 0.0
    require_explicit_profile: bool = False


def _default_thread_height(pitch: float, d_minor: float) -> float:
    """~65 % of pitch gives bold, visible teeth (user-requested 60-80 %)."""
    h = 0.65 * pitch
    return max(0.05, min(h, 0.35 * d_minor))


def _validate(shaft_spec: ShaftSpec, p: ThreadParams) -> ThreadParams:
    if p.pitch <= 0:
        raise ValueError(f"pitch must be > 0, got {p.pitch!r}")
    if p.length <= 0:
        raise ValueError(f"length must be > 0, got {p.length!r}")
    if p.start_from_head < 0:
        raise ValueError(f"start_from_head must be >= 0, got {p.start_from_head!r}")
    if p.starts < 1:
        raise ValueError(f"starts must be >= 1, got {p.starts!r}")
    if p.starts > 1:
        raise NotImplementedError("starts > 1 is not implemented yet.")
    if p.included_angle_deg <= 0 or p.included_angle_deg >= 179:
        raise ValueError(
            f"included_angle_deg must be in (0, 179), got {p.included_angle_deg!r}"
        )
    if p.thread_height is not None and p.thread_height <= 0:
        raise ValueError(f"thread_height must be > 0 when provided, got {p.thread_height!r}")

    has_tip = shaft_spec.tip_len > 0
    max_threadable = shaft_spec.L if has_tip else shaft_spec.L - 0.002
    if p.start_from_head + p.length > max_threadable + 1e-9:
        clamped = max(0.1, max_threadable - p.start_from_head)
        p = _replace(p, length=clamped)
    return p


def _twist_angle_deg(
    length: float, pitch: float, handedness: Literal["RH", "LH"],
) -> float:
    sign = 1.0 if handedness == "RH" else -1.0
    return sign * 360.0 * length / pitch


def _make_thread_profile(
    minor_r: float, major_r: float, half_w: float, z_offset: float,
) -> cq.Workplane:
    """D-shaped thread profile: arc from root through crest, straight close.

    Only 2 sharp edges exist (at root corners where the arc meets the
    straight line).  The crest is part of the smooth arc — no edge there.
    """
    return (
        cq.Workplane("XY")
        .workplane(offset=z_offset)
        .moveTo(minor_r, -half_w)
        .threePointArc((major_r, 0.0), (minor_r, half_w))
        .close()
    )


def apply_external_thread(
    core_shaft: cq.Workplane,
    shaft_spec: ShaftSpec,
    p: ThreadParams,
) -> cq.Workplane:
    """Apply a bold helical thread to a +Z-oriented shaft.

    The profile is a D-shaped arc spanning the full pitch width.  For
    screws with a conical tip the helix continues down the cone in
    scaled segments whose profile shrinks proportionally with the cone
    radius, reaching zero at the tip point.
    """
    p = _validate(shaft_spec, p)
    th = (
        p.thread_height
        if p.thread_height is not None
        else _default_thread_height(p.pitch, shaft_spec.d_minor)
    )

    minor_r = max(shaft_spec.d_minor / 2.0 + p.clearance - 0.02, 0.01)
    major_d = p.major_d if p.major_d is not None else shaft_spec.d_minor + 2.0 * th
    major_r = major_d / 2.0
    if major_r <= minor_r:
        return core_shaft

    half_w = p.pitch / 2.0
    sign = 1.0 if p.handedness == "RH" else -1.0

    shoulder_z = shaft_spec.L - shaft_spec.tip_len
    thread_end = p.start_from_head + p.length
    has_tip = shaft_spec.tip_len > 0 and thread_end > shoulder_z + 0.01

    cyl_len = (shoulder_z - p.start_from_head) if has_tip else p.length

    # ---- 1. Cylindrical section: one twist-extrude ----
    all_thread: cq.Workplane | None = None
    if cyl_len >= p.pitch * 0.25:
        cyl_profile = _make_thread_profile(minor_r, major_r, half_w, p.start_from_head)
        all_thread = cyl_profile.twistExtrude(
            cyl_len,
            _twist_angle_deg(cyl_len, p.pitch, p.handedness),
            combine=False,
        )

    # ---- 2. Tip taper: scaled segments following the cone ----
    if has_tip:
        tip_thread = _build_tip_segments(
            shaft_spec, p, minor_r, major_r, half_w, sign,
        )
        if tip_thread is not None:
            if all_thread is None:
                all_thread = tip_thread
            else:
                try:
                    all_thread = all_thread.union(tip_thread, clean=False)
                except Exception:
                    pass

    # ---- 3. Union with shaft ----
    if all_thread is not None:
        try:
            result = core_shaft.union(all_thread, clean=True).combine()
            if result.val().isValid() and result.val().Volume() > 1e-6:
                return result
        except Exception:
            pass

    return core_shaft


def _build_tip_segments(
    shaft_spec: ShaftSpec,
    p: ThreadParams,
    minor_r: float,
    major_r: float,
    half_w: float,
    sign: float,
) -> cq.Workplane | None:
    """Build thread segments that follow the tip cone.

    Uses 8 segments per helix turn for a smooth taper.  Each segment's
    profile is scaled by the cone radius at its start Z so the thread
    teeth shrink proportionally and reach zero at the tip.
    """
    shoulder_z = shaft_spec.L - shaft_spec.tip_len
    tip_len = shaft_spec.tip_len

    turns_in_tip = tip_len / p.pitch
    n_seg = max(12, int(math.ceil(turns_in_tip * 8)))
    seg_len = tip_len / n_seg
    min_useful_r = 0.03

    tip_thread: cq.Workplane | None = None

    for i in range(n_seg):
        seg_z = shoulder_z + i * seg_len
        scale = max(0.0, 1.0 - i / n_seg)

        seg_minor = minor_r * scale
        seg_major = major_r * scale

        if seg_major < min_useful_r or seg_major - seg_minor < 0.005:
            break

        try:
            seg_profile = _make_thread_profile(seg_minor, seg_major, half_w, seg_z)
        except Exception:
            continue

        seg_twist = _twist_angle_deg(seg_len, p.pitch, p.handedness)
        try:
            seg_solid = seg_profile.twistExtrude(seg_len, seg_twist, combine=False)
        except Exception:
            continue

        phase_deg = sign * 360.0 * (seg_z - p.start_from_head) / p.pitch
        seg_solid = seg_solid.rotate((0, 0, 0), (0, 0, 1), phase_deg)

        try:
            if seg_solid.val().Volume() < 1e-6:
                continue
        except Exception:
            continue

        if tip_thread is None:
            tip_thread = seg_solid
        else:
            try:
                tip_thread = tip_thread.union(seg_solid, clean=False)
            except Exception:
                continue

    if tip_thread is None:
        return None

    tip_env = (
        cq.Workplane("XZ")
        .moveTo(0.0, shoulder_z - 0.01)
        .lineTo(major_r + 0.05, shoulder_z - 0.01)
        .lineTo(0.0, shaft_spec.L)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )
    try:
        tip_thread = tip_thread.intersect(tip_env)
    except Exception:
        pass

    return tip_thread
