"""Test different rotations to find horizontal screw orientation."""
import re
from src.screwgen.assembly import make_screw_from_spec
from src.screwgen.search_parser import screw_spec_from_query
from cadquery import exporters
from pathlib import Path

out = Path("test_outputs")
out.mkdir(exist_ok=True)

q = (
    "screw flat head phillips head diameter 11.2 shank diameter 6.0 "
    "root diameter 5.0 length 25 tip length 2.5"
)
spec = screw_spec_from_query(q, apply_realism_checks=False)
screw = make_screw_from_spec(spec, include_thread_markers=False)

configs = {
    "A_current": {
        "rot": [(1,0,0,180), (0,1,0,-90)],
        "proj": (-0.15, 0.35, 1.0),
    },
    "B_add_z90": {
        "rot": [(1,0,0,180), (0,1,0,-90), (0,0,1,90)],
        "proj": (-0.15, 0.35, 1.0),
    },
    "C_tilt_horiz": {
        "rot": [(1,0,0,200), (0,1,0,-90), (0,0,1,90)],
        "proj": (0.15, 0.25, 1.0),
    },
    "D_simple": {
        "rot": [(0,1,0,90), (1,0,0,-25)],
        "proj": (0.0, -0.3, 1.0),
    },
    "E_catalog": {
        "rot": [(1,0,0,200), (0,0,1,90)],
        "proj": (-0.25, 0.15, 1.0),
    },
}

for name, cfg in configs.items():
    model = screw
    for ax_x, ax_y, ax_z, angle in cfg["rot"]:
        model = model.rotate((0,0,0), (ax_x, ax_y, ax_z), angle)
    svg_path = out / f"orient_{name}.svg"
    exporters.export(
        model, str(svg_path), exportType="SVG",
        opt={"projectionDir": cfg["proj"], "showAxes": False, "showHidden": False},
    )
    text = svg_path.read_text()
    w_m = re.search(r'width="([^"]+)"', text)
    h_m = re.search(r'height="([^"]+)"', text)
    w = float(w_m.group(1)) if w_m else 0
    h = float(h_m.group(1)) if h_m else 0
    print(f"{name}: SVG {w:.0f}x{h:.0f}  aspect={w/max(h,1):.2f}  -> {svg_path}")

print("Done!")
