# ScrewGen

## Project Overview
ScrewGen is a parametric screw generator built with CadQuery (OpenCascade/OCCT). It exports STEP (B-Rep) and STL (mesh) for CAD review and downstream workflows.

Implemented today:
- Heads: `flat`, `pan`, `button`, `hex`
- Drives: `hex(3)`, `phillips(4)`, `torx(6)`
- Shafts: minor-diameter cylinder + pointed tip
- Screw-level `ScrewSpec` with shaft region modeling (`Smooth` / `Thread`) for thread-ready planning
- Gallery exports, including sectioned views

Real helical thread geometry is not implemented yet.

## Features
- Parametric head/drive/shaft inputs
- Drive recess generated as a separate cut solid
- Region-aware screw specification for future partial/multi-thread layouts
- Placeholder thread-region sleeve markers (no helix) for validating region placement
- Robust boolean operations for cut/union workflows
- Preview/export harnesses for individual parts and combined galleries

## Repository Structure
```text
src/screwgen/
  __init__.py
  heads.py
  drives.py
  shaft.py
  assembly.py
  spec.py
  export.py
  preview/
    __init__.py
    preview_heads.py
    preview_drives.py
    preview_shafts.py
    preview_gallery.py
    preview_thread_regions.py

tests/
  test_heads.py
  test_drives.py
  test_shafts.py
  test_assembly.py
  test_spec_regions.py
```

Root-level compatibility wrappers are kept for legacy commands (`preview.py`, `preview_drives.py`, `preview_shafts.py`, `preview_screws.py`).

## Installation
Assumptions:
- Python 3.11+
- A runtime compatible with CadQuery wheels

### Option A: editable install (recommended)
```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .
```

### Option B: requirements install
```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
```

## Usage
Run preview modules:

```bash
python -m screwgen.preview.preview_heads
python -m screwgen.preview.preview_drives
python -m screwgen.preview.preview_shafts
python -m screwgen.preview.preview_gallery
python -m screwgen.preview.preview_thread_regions
python -m screwgen.preview.preview_threads
python -m screwgen.preview.preview_threads_gallery
```

Defaults are STEP-first for speed. Add `--stl` on preview commands when mesh exports are needed.
For threaded gallery:
- quick review: `python -m screwgen.preview.preview_threads_gallery`
- include individual screws: `... --individual`
- include STL: `... --individual --stl`

Legacy wrappers remain valid:

```bash
python preview.py
python preview_drives.py
python preview_shafts.py
python preview_screws.py
python preview_thread_regions.py
python preview_threads.py
python preview_threads_gallery.py
```

### Output Conventions
Exports are written under `out/` with deterministic names:
- `out/heads/step`, `out/heads/stl`
- `out/drives/step`, `out/drives/stl`
- `out/shafts/step`, `out/shafts/stl`
- `out/screws/step`, `out/screws/stl`
- `out/galleries/step`
- `out/galleries/sectioned/step`

Examples:
- `head_<type>.step`, `head_<type>.stl`
- `screw_<head>__<drive>__A.step`
- `screw_gallery.step`, `screw_gallery_section.step`
- `thread_region_gallery.step`, `thread_region_gallery_section.step`

## Testing
Run all tests:

```bash
pytest
```

## Roadmap
- Real helical thread generation from region definitions
- Standards-aligned pitch and size tables
- Automated engineering drawing generation
- Optional structured input / text parsing interface

## Non-goals / Notes
- No confidential information is stored in this repository.
- Geometry is not standards-certified yet; values are practical and preview-oriented.

# ScrewGen

## Project Overview
ScrewGen is a parametric screw generator built with CadQuery (OpenCascade/OCCT). It generates CAD solids as STEP (B-Rep) and STL (mesh) for review and downstream workflows.

Current implemented geometry:
- Heads: `flat`, `pan`, `button`, `hex`
- Drives: `hex(3)`, `phillips(4)`, `torx(6)`
- Shafts: minor-diameter cylinder + pointed tip
- Gallery exports for CAD review (including sectioned gallery)

Threads are not implemented yet.

## Features
- Parametric head/drive/shaft inputs
- Drive recess implemented as a separate cut solid
- Robust boolean operations for cut/union workflows
- Preview/export harnesses for:
  - head-only
  - drive-only and head+drive
  - shaft-only and head+shaft
  - full representative screw gallery + section

## Repository Structure
```text
src/screwgen/
  __init__.py
  heads.py
  drives.py
  shaft.py
  assembly.py
  export.py
  preview/
    __init__.py
    preview_heads.py
    preview_drives.py
    preview_shafts.py
    preview_gallery.py

tests/
  test_heads.py
  test_drives.py
  test_shafts.py
  test_assembly.py
```

Root-level compatibility wrappers are kept for legacy commands (`preview.py`, `preview_drives.py`, `preview_shafts.py`, `preview_screws.py`, and module wrappers like `head.py`).

## Installation
Assumptions:
- Python 3.11+
- A working C++ runtime compatible with CadQuery wheels

### Option A: editable install (recommended)
```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .
```

### Option B: requirements install
```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
```

## Usage
Run preview modules directly:

```bash
python -m screwgen.preview.preview_heads
python -m screwgen.preview.preview_drives
python -m screwgen.preview.preview_shafts
python -m screwgen.preview.preview_gallery
```

Legacy wrapper commands remain valid:

```bash
python preview.py
python preview_drives.py
python preview_shafts.py
python preview_screws.py
```

### Output Conventions
Exports are written to `outputs/` with deterministic names, for example:
- `head_<type>.step`, `head_<type>.stl`
- `drive_<type>_<size>.step`, `drive_<type>_<size>.stl`
- `screw_<head>__<drive>__A.step` (representative gallery variants)
- `screw_gallery.step`, `screw_gallery_section.step`

## Testing
Run all tests:

```bash
pytest
```

## Roadmap
- Thread module (helical thread generation on shaft core)
- Standards-aligned sizing refinement for head/drive dimensions
- Automated engineering drawing generation
- Optional structured inputs / text parsing interface

## Non-goals / Notes
- No confidential information is stored in this repository.
- Geometry is not standards-certified yet; values are practical/preview-oriented.

# Parametric Screw Head Generator

Generates parametric screw heads using CadQuery (OpenCASCADE B-Rep kernel).

## Supported Head Types

| Type     | Description                           |
|----------|---------------------------------------|
| `flat`   | Countersunk cone (apex at top)        |
| `pan`    | Cylinder + shallow spherical dome     |
| `button` | Cylinder + pronounced spherical dome  |
| `hex`    | Hexagonal prism                       |

## Coordinate Convention

- Head centered on Z axis
- Underside at Z = 0
- Head occupies Z in [0, h]

## Usage

```python
from head import make_head

solid = make_head({"type": "pan", "d": 8, "h": 4})
```

## Preview Harness

```bash
python preview.py
```

Generates individual STEP/STL files and a combined gallery STEP in `outputs/`.

## Tests

```bash
python -m pytest test_head.py -v
```

## Requirements

- Python 3.11+
- CadQuery 2.6+

