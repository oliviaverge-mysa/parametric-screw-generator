"""Top-level screw specification and shaft-region model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

HeadType = Literal["flat", "pan", "button", "hex"]
DriveType = Literal["hex", "phillips", "torx"]
DriveFit = Literal["nominal", "scale_to_head", "max_that_fits"]
Handedness = Literal["RH", "LH"]


@dataclass(frozen=True)
class HeadSpec:
    type: HeadType
    d: float
    h: float
    acrossFlats: float | None = None


@dataclass(frozen=True)
class DriveSpec:
    type: DriveType
    size: Literal[3, 4, 6]
    depth: float | None = None
    fit: DriveFit = "max_that_fits"
    clearance: float = 0.05


@dataclass(frozen=True)
class ShaftSpec:
    d_minor: float
    L: float
    tip_len: float


@dataclass(frozen=True)
class RegionSpec:
    length: float


@dataclass(frozen=True)
class SmoothRegionSpec(RegionSpec):
    pass


@dataclass(frozen=True)
class ThreadRegionSpec(RegionSpec):
    pitch: float
    starts: int = 1
    handedness: Handedness = "RH"
    start_offset: float = 0.0
    major_d: float | None = None


Region = Union[SmoothRegionSpec, ThreadRegionSpec]


@dataclass(frozen=True)
class ScrewSpec:
    head: HeadSpec
    drive: DriveSpec | None
    shaft: ShaftSpec
    regions: list[Region]


def expand_regions(spec: ScrewSpec) -> list[Region]:
    """Return regions normalized to shaft length.

    If region lengths sum to less than shaft length, append a Smooth tail so
    the region plan fully spans the shaft length in a deterministic way.
    """
    used = sum(r.length for r in spec.regions)
    remainder = spec.shaft.L - used
    out = list(spec.regions)
    if remainder > 1e-9:
        out.append(SmoothRegionSpec(length=remainder))
    return out


def validate_screw_spec(spec: ScrewSpec) -> None:
    if spec.head.d <= 0:
        raise ValueError(f"head.d must be > 0, got {spec.head.d!r}")
    if spec.head.h <= 0:
        raise ValueError(f"head.h must be > 0, got {spec.head.h!r}")
    if spec.head.type == "hex" and spec.head.acrossFlats is not None and spec.head.acrossFlats <= 0:
        raise ValueError(f"head.acrossFlats must be > 0 when provided, got {spec.head.acrossFlats!r}")
    if spec.shaft.d_minor <= 0:
        raise ValueError(f"shaft.d_minor must be > 0, got {spec.shaft.d_minor!r}")
    if spec.shaft.L <= 0:
        raise ValueError(f"shaft.L must be > 0, got {spec.shaft.L!r}")
    if spec.shaft.tip_len <= 0 or spec.shaft.tip_len >= spec.shaft.L:
        raise ValueError(
            f"shaft.tip_len must be > 0 and < shaft.L, got tip_len={spec.shaft.tip_len!r}, L={spec.shaft.L!r}"
        )
    if spec.drive is not None:
        if spec.drive.depth is not None and spec.drive.depth <= 0:
            raise ValueError(f"drive.depth must be > 0 when provided, got {spec.drive.depth!r}")
        if spec.drive.clearance < 0:
            raise ValueError(f"drive.clearance must be >= 0, got {spec.drive.clearance!r}")
    if len(spec.regions) == 0:
        raise ValueError("regions must contain at least one region.")

    total = 0.0
    for i, region in enumerate(spec.regions):
        if region.length <= 0:
            raise ValueError(f"regions[{i}].length must be > 0, got {region.length!r}")
        total += region.length
        if isinstance(region, ThreadRegionSpec):
            if region.pitch <= 0:
                raise ValueError(f"regions[{i}].pitch must be > 0, got {region.pitch!r}")
            if region.starts <= 0:
                raise ValueError(f"regions[{i}].starts must be > 0, got {region.starts!r}")
            if region.major_d is not None and region.major_d <= spec.shaft.d_minor:
                raise ValueError(
                    f"regions[{i}].major_d must be > shaft.d_minor when provided, "
                    f"got major_d={region.major_d!r}, d_minor={spec.shaft.d_minor!r}"
                )
    if total > spec.shaft.L + 1e-9:
        raise ValueError(
            f"sum(region.length) must be <= shaft.L, got sum={total!r}, shaft.L={spec.shaft.L!r}"
        )

