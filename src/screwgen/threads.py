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


def _validate(shaft_spec: ShaftSpec, p: ThreadParams) -> ThreadParams:
    """Validate and return *p*, clamping thread length if it overflows the shaft."""
    from dataclasses import replace as _replace

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

    has_tip = shaft_spec.tip_len > 0
    max_threadable = shaft_spec.L if has_tip else shaft_spec.L - 0.002
    if p.start_from_head + p.length > max_threadable + 1e-9:
        clamped = max(0.1, max_threadable - p.start_from_head)
        p = _replace(p, length=clamped)
    return p


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


def _taper_threads_into_tip(
    result: cq.Workplane,
    shaft_spec: ShaftSpec,
    p: ThreadParams,
    thread_height: float,
) -> cq.Workplane:
    """Add tapered thread ridges that follow the tip cone.

    Splits the tip into segments with scaled profiles so threads shrink
    naturally toward the point.  All segments are merged into a single
    solid first, then unioned once with the shaft for performance.
    """
    major_d = p.major_d if p.major_d is not None else shaft_spec.d_minor + 2.0 * thread_height
    major_r_base = major_d / 2.0
    minor_r_base = max(shaft_spec.d_minor / 2.0 + p.clearance - 0.02, 0.01)
    shoulder_z = shaft_spec.L - shaft_spec.tip_len
    tip_len = shaft_spec.tip_len

    overlap = min(0.15, tip_len * 0.1)
    cone_start = shoulder_z - overlap
    cone_len = tip_len + overlap

    min_useful_r = 0.08
    n_segments = max(3, min(6, int(math.ceil(cone_len / p.pitch))))
    seg_len = cone_len / n_segments
    base_phase = 360.0 * (cone_start - p.start_from_head) / p.pitch
    if p.handedness == "LH":
        base_phase = -base_phase

    all_tip_threads: cq.Workplane | None = None

    for i in range(n_segments):
        seg_start = cone_start + i * seg_len
        seg_mid = seg_start + seg_len / 2.0
        t = (seg_mid - cone_start) / cone_len
        scale = max(0.0, 1.0 - t)
        local_major_r = major_r_base * scale
        local_minor_r = minor_r_base * scale
        if local_major_r < min_useful_r or local_minor_r >= local_major_r - 0.01:
            break

        half_w = _tri_half_width(local_major_r - local_minor_r, p.included_angle_deg)
        if half_w < 0.01:
            break

        ridge_profile = (
            cq.Workplane("XY")
            .workplane(offset=seg_start)
            .polyline(
                [
                    (local_minor_r, -half_w),
                    (local_major_r, 0.0),
                    (local_minor_r, half_w),
                ]
            )
            .close()
        )

        twist = _twist_angle_deg(seg_len, p.pitch, p.handedness)
        seg_ridges = ridge_profile.twistExtrude(seg_len, twist, combine=False)

        seg_phase = base_phase + 360.0 * (i * seg_len) / p.pitch
        if p.handedness == "LH":
            seg_phase = -seg_phase + 2 * base_phase
        seg_ridges = seg_ridges.rotate((0, 0, 0), (0, 0, 1), seg_phase)

        env_r_start = major_r_base * max(0.0, 1.0 - (seg_start - cone_start) / cone_len) + 0.01
        env_r_end = major_r_base * max(0.0, 1.0 - (seg_start + seg_len - cone_start) / cone_len) + 0.01
        envelope = (
            cq.Workplane("XY")
            .workplane(offset=seg_start)
            .circle(env_r_start)
            .workplane(offset=seg_len)
            .circle(max(0.01, env_r_end))
            .loft()
        )

        try:
            clipped = seg_ridges.intersect(envelope)
            if not clipped.val().isValid() or clipped.val().Volume() < 1e-6:
                continue
            if all_tip_threads is None:
                all_tip_threads = clipped
            else:
                all_tip_threads = all_tip_threads.union(clipped, clean=False)
        except Exception:
            continue

    if all_tip_threads is not None:
        result = result.union(all_tip_threads, clean=True)
    return result


def apply_external_thread(core_shaft: cq.Workplane, shaft_spec: ShaftSpec, p: ThreadParams) -> cq.Workplane:
    """Apply external thread geometry on a +Z-oriented shaft.

    Expected local frame:
    - attachment plane at z=0
    - shaft extends toward +Z
    """
    from dataclasses import replace as _replace

    p = _validate(shaft_spec, p)
    thread_height = p.thread_height if p.thread_height is not None else _default_thread_height(
        p.pitch, shaft_spec.d_minor
    )

    thread_end = p.start_from_head + p.length
    shoulder_z = shaft_spec.L - shaft_spec.tip_len
    needs_tip_taper = shaft_spec.tip_len > 0 and thread_end > shoulder_z + 1e-9

    if p.mode == "add":
        if needs_tip_taper:
            cyl_length = max(0.1, shoulder_z - p.start_from_head)
            cyl_p = _replace(p, length=cyl_length)
            thread_solid = _build_add_thread_solid(shaft_spec, cyl_p, thread_height)
            result = core_shaft.union(thread_solid, clean=True).combine()
            try:
                tapered = _taper_threads_into_tip(result, shaft_spec, p, thread_height)
                if tapered.val().isValid() and tapered.val().Volume() > 1e-6:
                    result = tapered
            except Exception:
                pass
        else:
            thread_solid = _build_add_thread_solid(shaft_spec, p, thread_height)
            result = core_shaft.union(thread_solid, clean=True).combine()
        return result

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
    try:
        threaded_segment = major_segment.cut(groove)
    except Exception:
        # Boolean can fail for some extreme inferred thread combinations.
        ridge = _build_add_thread_solid(shaft_spec, p, thread_height)
        return core_shaft.union(ridge, clean=True).combine()
    result = core_shaft.union(threaded_segment, clean=True).combine()
    if not result.val().isValid():
        # Fallback to add-mode ridge when groove cut is numerically unstable.
        ridge = _build_add_thread_solid(shaft_spec, p, thread_height)
        result = core_shaft.union(ridge, clean=True).combine()
    return result

