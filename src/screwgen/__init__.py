"""screwgen package."""

from .heads import HeadParams, HeadType, head_shaft_attach_z, head_tool_z, make_head
from .drives import DriveParams, DriveSize, DriveType, make_drive_cut
from .shaft import ShaftParams, attach_shaft_to_head, make_shaft
from .assembly import (
    apply_drive_to_head,
    build_thread_region_markers,
    make_screw,
    make_screw_from_spec,
    shaft_axis_for_head,
)
from .spec import (
    DriveSpec,
    HeadSpec,
    RegionSpec,
    ScrewSpec,
    ShaftSpec,
    SmoothRegionSpec,
    ThreadRegionSpec,
    expand_regions,
    validate_screw_spec,
)
from .threads import ThreadParams, apply_external_thread

