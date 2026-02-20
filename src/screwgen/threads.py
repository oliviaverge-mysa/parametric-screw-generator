"""External thread geometry (v1): single continuous helical V-profile region."""

from __future__ import annotations

import math
from dataclasses import dataclass
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
    mode: Literal["add", "cut"] = "cut"
    clearance: float = 0.0
    require_explicit_profile: bool = False


def _default_thread_height(pitch: float, d_minor: float) -> float:
    # Practical preview default: 0.3*pitch, clamped to a sane range.
    h = 0.3 * pitch
    return max(0.05, min(h, 0.45 * pitch, 0.35 * d_minor))


def _validate(shaft_spec: ShaftSpec, p: ThreadParams) -> None:
    if p.pitch <= 0:
        raise ValueError(f"pitch must be > 0, got {p.pitch!r}")
    if p.length <= 0:
        raise ValueError(f"length must be > 0, got {p.length!r}")
    if p.start_from_head < 0:
        raise ValueError(f"start_from_head must be >= 0, got {p.start_from_head!r}")
    if p.starts < 1:
        raise ValueError(f"starts must be >= 1, got {p.starts!r}")
    if p.starts > 1:
        raise NotImplementedError("starts > 1 is not implemented yet in v1 thread geometry.")
    if p.mode not in ("add", "cut"):
        raise ValueError(f"mode must be 'add' or 'cut', got {p.mode!r}")
    if p.included_angle_deg <= 0 or p.included_angle_deg >= 179:
        raise ValueError(
            f"included_angle_deg must be in (0, 179), got {p.included_angle_deg!r}"
        )
    if p.thread_height is not None and p.thread_height <= 0:
        raise ValueError(f"thread_height must be > 0 when provided, got {p.thread_height!r}")
    if p.require_explicit_profile and p.thread_height is None and p.major_d is None:
        raise ValueError(
            "When require_explicit_profile=True, provide thread_height or major_d."
        )

    max_threadable = shaft_spec.L - shaft_spec.tip_len
    if p.start_from_head + p.length > max_threadable + 1e-9:
        raise ValueError(
            "start_from_head + length must be <= shaft_spec.L - shaft_spec.tip_len, "
            f"got {p.start_from_head + p.length!r} > {max_threadable!r}"
        )


def _twist_angle_deg(length: float, pitch: float, handedness: Literal["RH", "LH"]) -> float:
    turns = length / pitch
    sign = 1.0 if handedness == "RH" else -1.0
    return sign * 360.0 * turns


def _tri_half_width(height: float, included_angle_deg: float) -> float:
    half_angle_rad = math.radians(included_angle_deg / 2.0)
    return height / math.tan(half_angle_rad)


def _build_add_thread_solid(shaft_spec: ShaftSpec, p: ThreadParams, thread_height: float) -> cq.Workplane:
    minor_r = max(shaft_spec.d_minor / 2.0 + p.clearance - 0.02, 0.01)
    major_d = p.major_d if p.major_d is not None else shaft_spec.d_minor + 2.0 * thread_height
    major_r = major_d / 2.0
    if major_r <= minor_r:
        raise ValueError(
            f"major radius must exceed minor radius for add mode, got major_r={major_r}, minor_r={minor_r}"
        )

    half_w = _tri_half_width(thread_height, p.included_angle_deg)
    profile = (
        cq.Workplane("XY")
        .workplane(offset=p.start_from_head)
        .polyline(
            [
                (minor_r, -half_w),
                (major_r, 0.0),
                (minor_r, half_w),
            ]
        )
        .close()
    )
    return profile.twistExtrude(
        p.length,
        _twist_angle_deg(p.length, p.pitch, p.handedness),
        combine=False,
    )


def _build_cut_groove_solid(shaft_spec: ShaftSpec, p: ThreadParams, thread_height: float) -> cq.Workplane:
    minor_r = max(shaft_spec.d_minor / 2.0 + p.clearance - 0.03, 0.01)
    major_d = p.major_d if p.major_d is not None else shaft_spec.d_minor + 2.0 * thread_height
    major_r = major_d / 2.0
    if major_r <= minor_r:
        raise ValueError(
            f"major radius must exceed minor radius for cut mode, got major_r={major_r}, minor_r={minor_r}"
        )

    half_w = _tri_half_width(thread_height, p.included_angle_deg)
    groove_profile = (
        cq.Workplane("XY")
        .workplane(offset=p.start_from_head)
        .polyline(
            [
                (major_r, -half_w),
                (minor_r, 0.0),
                (major_r, half_w),
            ]
        )
        .close()
    )
    return groove_profile.twistExtrude(
        p.length,
        _twist_angle_deg(p.length, p.pitch, p.handedness),
        combine=False,
    )


def apply_external_thread(core_shaft: cq.Workplane, shaft_spec: ShaftSpec, p: ThreadParams) -> cq.Workplane:
    """Apply external thread geometry on a +Z-oriented shaft.

    Expected local frame:
    - attachment plane at z=0
    - shaft extends toward +Z
    """
    _validate(shaft_spec, p)
    thread_height = p.thread_height if p.thread_height is not None else _default_thread_height(
        p.pitch, shaft_spec.d_minor
    )

    if p.mode == "add":
        thread_solid = _build_add_thread_solid(shaft_spec, p, thread_height)
        return core_shaft.union(thread_solid, clean=True).combine()

    # mode == "cut"
    major_d = p.major_d if p.major_d is not None else shaft_spec.d_minor + 2.0 * thread_height
    major_r = major_d / 2.0
    if major_r <= shaft_spec.d_minor / 2.0:
        raise ValueError(
            f"major_d must produce radius > d_minor/2 for cut mode, got major_d={major_d!r}"
        )
    major_segment = (
        cq.Workplane("XY")
        .workplane(offset=p.start_from_head)
        .circle(major_r)
        .extrude(p.length)
    )
    groove = _build_cut_groove_solid(shaft_spec, p, thread_height)
    threaded_segment = major_segment.cut(groove)
    result = core_shaft.union(threaded_segment, clean=True).combine()
    if not result.val().isValid():
        # Fallback to add-mode ridge when groove cut is numerically unstable.
        ridge = _build_add_thread_solid(shaft_spec, p, thread_height)
        result = core_shaft.union(ridge, clean=True).combine()
    return result

