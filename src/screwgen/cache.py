"""Memoized shape builders for repeated preview/assembly generation."""

from __future__ import annotations

from functools import lru_cache

import cadquery as cq

from .drives import DriveParams, make_drive_cut
from .heads import HeadParams, make_head
from .shaft import ShaftParams, make_shaft
from .spec import ShaftSpec
from .threads import ThreadParams, apply_external_thread


def _head_key(p: HeadParams) -> tuple:
    return (
        p["type"],
        float(p["d"]),
        float(p["h"]),
        None if p.get("acrossFlats") is None else float(p["acrossFlats"]),
    )


@lru_cache(maxsize=128)
def _cached_head_shape(key: tuple) -> cq.Shape:
    htype, d, h, af = key
    params: HeadParams = {"type": htype, "d": d, "h": h}  # type: ignore[typeddict-item]
    if af is not None:
        params["acrossFlats"] = af
    return make_head(params).val()


def cached_make_head(p: HeadParams) -> cq.Workplane:
    return cq.Workplane(obj=_cached_head_shape(_head_key(p)))


@lru_cache(maxsize=256)
def _cached_drive_cut_shape(p: DriveParams) -> cq.Shape:
    return make_drive_cut(p).val()


def cached_make_drive_cut(p: DriveParams) -> cq.Workplane:
    return cq.Workplane(obj=_cached_drive_cut_shape(p))


@lru_cache(maxsize=128)
def _cached_shaft_shape(p: ShaftParams) -> cq.Shape:
    return make_shaft(p).val()


def cached_make_shaft(p: ShaftParams) -> cq.Workplane:
    return cq.Workplane(obj=_cached_shaft_shape(p))


@lru_cache(maxsize=128)
def _cached_threaded_shaft_shape(shaft_spec: ShaftSpec, p: ThreadParams) -> cq.Shape:
    shaft = make_shaft(ShaftParams(d_minor=shaft_spec.d_minor, L=shaft_spec.L, tip_len=shaft_spec.tip_len))
    shaft_up = shaft.rotate((0, 0, 0), (1, 0, 0), 180)
    shaft_up = apply_external_thread(shaft_up, shaft_spec, p)
    return shaft_up.rotate((0, 0, 0), (1, 0, 0), 180).val()


def cached_make_threaded_shaft(shaft_spec: ShaftSpec, p: ThreadParams) -> cq.Workplane:
    return cq.Workplane(obj=_cached_threaded_shaft_shape(shaft_spec, p))

