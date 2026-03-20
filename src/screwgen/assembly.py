"""Assembly helpers for head + drive + shaft."""

from __future__ import annotations

from dataclasses import replace

import cadquery as cq

from .cache import cached_make_drive_cut, cached_make_head, cached_make_shaft
from .drives import DriveParams
from .heads import HeadParams, head_tool_z
from .shaft import ShaftParams, attach_shaft_to_head, resolve_shaft_attach_z
from .spec import (
    DriveSpec,
    HeadSpec,
    Region,
    ScrewSpec,
    ShaftSpec,
    ThreadRegionSpec,
    expand_regions,
    validate_screw_spec,
)
from .threads import ThreadParams, apply_external_thread
from .search_parser import PromptFn, screw_spec_from_query

_THREAD_SLEEVE_RADIAL_THICKNESS = 0.2


def apply_drive_to_head(head: cq.Workplane, p: DriveParams, head_params: HeadParams | None = None) -> cq.Workplane:
    bb = head.val().BoundingBox()
    inferred_head_d = max(bb.xmax - bb.xmin, bb.ymax - bb.ymin)
    tool_z = head_tool_z(head_params) if head_params is not None else bb.zmax
    is_flat = head_params is not None and head_params["type"] == "flat"
    p_effective = replace(
        p,
        topZ=(max(tool_z, p.eps) if is_flat else tool_z),
        head_d=(p.head_d if p.head_d is not None else inferred_head_d),
    )
    cut = cached_make_drive_cut(p_effective)
    if is_flat:
        cut = cut.mirror("XY")
    return head.cut(cut)


def _head_params_from_spec(h: HeadSpec) -> HeadParams:
    out: HeadParams = {"type": h.type, "d": h.d, "h": h.h}
    if h.acrossFlats is not None:
        out["acrossFlats"] = h.acrossFlats
    return out


def _drive_params_from_spec(d: DriveSpec, head_params: HeadParams) -> DriveParams:
    head_d = float(head_params["d"])
    head_h = float(head_params["h"])
    depth = d.depth if d.depth is not None else min(3.0, 0.50 * head_h)
    return DriveParams(
        type=d.type,
        size=d.size,
        depth=depth,
        topZ=head_tool_z(head_params),
        fit=d.fit,
        clearance=d.clearance,
        head_d=head_d,
        slotted=d.slotted,
    )


def _shaft_params_from_spec(s: ShaftSpec, fastener_type: str) -> ShaftParams:
    tip_style = "flat" if fastener_type == "bolt" else "pointed"
    return ShaftParams(d_minor=s.d_minor, L=s.L, tip_len=s.tip_len, tip_style=tip_style)


def shaft_axis_for_head(head_params: HeadParams, shaft_radius: float) -> tuple[float, int]:
    """Return (attach_z, direction_sign) for shaft-away axis.

    direction_sign is +1 when shaft extends toward +Z, -1 toward -Z.
    """
    attach_z = resolve_shaft_attach_z(head_params, shaft_radius)
    direction_sign = +1 if head_params["type"] == "flat" else -1
    return attach_z, direction_sign


def _thread_marker_major_d(region: ThreadRegionSpec, shaft_d_minor: float) -> float:
    if region.major_d is not None:
        return region.major_d
    return shaft_d_minor + 0.15 * shaft_d_minor


def _build_thread_region_marker(
    *,
    attach_z: float,
    direction_sign: int,
    offset: float,
    length: float,
    shaft_d_minor: float,
    major_d: float,
) -> cq.Workplane:
    r_inner = shaft_d_minor / 2.0
    r_outer_nominal = major_d / 2.0
    r_outer = max(r_outer_nominal, r_inner + _THREAD_SLEEVE_RADIAL_THICKNESS)
    z_start = attach_z + direction_sign * offset
    sleeve = cq.Workplane("XY").workplane(offset=z_start).circle(r_outer).circle(r_inner).extrude(
        direction_sign * length
    )
    return sleeve


def _build_thread_region_markers(
    spec: ScrewSpec,
    head_params: HeadParams,
) -> cq.Workplane | None:
    shaft_radius = spec.shaft.d_minor / 2.0
    attach_z, direction_sign = shaft_axis_for_head(head_params, shaft_radius)
    offset = 0.0
    markers: cq.Workplane | None = None
    for region in expand_regions(spec):
        if isinstance(region, ThreadRegionSpec):
            marker = _build_thread_region_marker(
                attach_z=attach_z,
                direction_sign=direction_sign,
                offset=offset,
                length=region.length,
                shaft_d_minor=spec.shaft.d_minor,
                major_d=_thread_marker_major_d(region, spec.shaft.d_minor),
            )
            markers = marker if markers is None else markers.union(marker, clean=True)
        offset += region.length
    return markers


def build_thread_region_markers(spec: ScrewSpec) -> cq.Workplane | None:
    """Build sleeve markers for thread regions in assembled coordinates."""
    validate_screw_spec(spec)
    return _build_thread_region_markers(spec, _head_params_from_spec(spec.head))


def make_screw_from_spec(spec: ScrewSpec, include_thread_markers: bool = True) -> cq.Workplane:
    validate_screw_spec(spec)
    head_params = _head_params_from_spec(spec.head)
    shaft_params = _shaft_params_from_spec(spec.shaft, spec.fastener_type)
    head = cached_make_head(head_params)
    if spec.drive is not None:
        head = apply_drive_to_head(head, _drive_params_from_spec(spec.drive, head_params), head_params)
    shaft = cached_make_shaft(shaft_params)
    # Thread math is defined in +Z shaft-local coordinates; convert in/out.
    shaft_up = shaft.rotate((0, 0, 0), (1, 0, 0), 180)
    thread_start = 0.0
    shoulder_z = spec.shaft.L - spec.shaft.tip_len
    for region in expand_regions(spec):
        if isinstance(region, ThreadRegionSpec):
            effective_length = region.length
            if (
                spec.fastener_type == "screw"
                and spec.shaft.tip_len > 0
                and thread_start + region.length >= shoulder_z - 0.5
            ):
                effective_length = spec.shaft.L - thread_start
            shaft_up = apply_external_thread(
                shaft_up,
                spec.shaft,
                ThreadParams(
                    pitch=region.pitch,
                    length=effective_length,
                    start_from_head=thread_start,
                    included_angle_deg=60.0,
                    major_d=region.major_d,
                    thread_height=region.thread_height,
                    handedness=region.handedness,
                    starts=region.starts,
                    mode="add",
                ),
            )
        thread_start += region.length
    shaft = shaft_up.rotate((0, 0, 0), (1, 0, 0), 180)

    screw = attach_shaft_to_head(head, head_params, shaft)
    if not include_thread_markers:
        return screw
    markers = _build_thread_region_markers(spec, head_params)
    if markers is None:
        return screw
    with_markers = screw.union(markers, clean=True).combine()
    if not with_markers.val().isValid():
        return screw
    return with_markers


def make_screw(
    spec_or_head_params: ScrewSpec | HeadParams,
    drive_params: DriveParams | None = None,
    shaft_params: ShaftParams | None = None,
) -> cq.Workplane:
    """Build full screw.

    Supported forms:
    - make_screw(ScrewSpec, ...)
    - make_screw(head_params, drive_params, shaft_params) legacy form
    """
    if isinstance(spec_or_head_params, ScrewSpec):
        return make_screw_from_spec(spec_or_head_params, include_thread_markers=True)
    if drive_params is None or shaft_params is None:
        raise ValueError("Legacy make_screw form requires head_params, drive_params, and shaft_params.")
    head = cached_make_head(spec_or_head_params)
    head_with_drive = apply_drive_to_head(head, drive_params, spec_or_head_params)
    shaft = cached_make_shaft(shaft_params)
    return attach_shaft_to_head(head_with_drive, spec_or_head_params, shaft)


def make_screw_from_query(query: str, prompt: PromptFn | None = None) -> cq.Workplane:
    """Build screw from plain-text query, prompting for missing dimensions when needed."""
    spec = screw_spec_from_query(query, prompt=prompt)
    return make_screw_from_spec(spec, include_thread_markers=True)

