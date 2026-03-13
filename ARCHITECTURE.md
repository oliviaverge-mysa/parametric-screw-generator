# Architecture

## Overview

The system generates parametric threaded fasteners from plain-text descriptions or uploaded images, then exports production-ready CAD files. It consists of a Python backend (FastAPI + CadQuery) and a vanilla JS/CSS/HTML frontend.

## High-Level Flow

```
User input (text or image)
       │
       ▼
  ┌─────────────┐     ┌──────────────┐
  │ search_parser│ ──▶ │   ScrewSpec  │
  │  (NLP parse) │     │  (data model)│
  └─────────────┘     └──────┬───────┘
       │                      │
  Image path:                 ▼
  ┌─────────────┐     ┌──────────────┐
  │  CV pipeline │     │   assembly   │
  │ (webapp.py)  │     │  (CadQuery)  │
  └─────────────┘     └──────┬───────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  Export pipeline  │
                    │ STEP/STL/SVG/PDF │
                    └──────────────────┘
```

## Core Modules

### `spec.py` — Data Models
Immutable dataclasses defining the fastener specification:
- `ScrewSpec` — top-level container
- `HeadSpec` — head type, diameter, height, hex across-flats
- `DriveSpec` — drive type, size, fit mode
- `ShaftSpec` — minor diameter, length, tip length
- `ThreadRegionSpec` / `SmoothRegionSpec` — thread span definitions

### `search_parser.py` — Natural Language Parser
Converts free-text queries into `ScrewSpec` objects:
- Regex-based dimension extraction (diameter, length, pitch, etc.)
- Typo normalization (`bold` → `bolt`, `lenght` → `length`)
- Interactive prompts for missing values (screw/bolt, drive type)
- Realism checks with confirmation flow
- `apply_realism_checks` flag allows image-derived specs to skip validation

### `heads.py` — Head Geometry
CadQuery solids for each head type:
- `flat` — countersunk cone
- `pan` — low-profile dome
- `button` — taller dome with fillet
- `hex` — hexagonal prism

### `drives.py` — Drive Recess Geometry
CadQuery cut tools for each drive type:
- `hex` — hexagonal socket
- `phillips` — cross-shaped recess
- `torx` — six-pointed star
- `square` — Robertson square recess

### `shaft.py` — Shaft Geometry
Cylindrical shaft with configurable tip:
- `pointed` — conical tip (screws)
- `flat` — blunt end (bolts)

### `threads.py` — Thread Geometry
Applies external helical threads to shaft geometry. Supports single or multiple thread regions along the shaft length.

### `assembly.py` — Fastener Assembly
Combines head + drive + shaft + threads into a single solid. Handles the full build pipeline including thread region application.

### `cache.py` — Shape Cache
LRU-cached wrappers around geometry builders to avoid redundant computation during gallery/preview generation.

### `export.py` — File Export
Helpers for writing STEP and STL files with consistent output paths.

### `webapp.py` — Web Application
The largest module (~2,800 lines), containing:

**API Layer (FastAPI)**
- Chat CRUD endpoints (`/api/chats`, `/api/chats/{id}/message`, etc.)
- Image upload endpoint (`/api/chats/{id}/image`)
- File download route with SVG post-processing
- Static file serving for the frontend

**Chat State Machine**
- `ChatState` tracks conversation, pending questions, and generated files
- Multi-step flows: screw/bolt selection → drive selection → generation → nut offer
- Button-based interactive prompts rendered in the frontend

**Image Detection Pipeline**
- Subject extraction from photos/screenshots (edge-based card detection)
- Profile analysis: contour elongation, head ratio, head drop/taper
- Drive detection: line counting, template correlation, contour solidity, radial lobe analysis
- Post-classification overrides for common misclassification patterns
- Optional multimodal vision model integration

**Drawing Generation**
- Engineering drawing PDFs with orthographic views and dimensions
- SVG preview post-processing (fill, stroke normalization, viewBox injection)

**Nut Generation**
- Hex and square nut geometry from fastener spec
- Internal thread via helical boolean subtraction

## Frontend

### `index.html`
Single-page app with three views:
- **Landing page** — search bar + image upload button
- **Chat panel** — message bubbles, preview cards, button prompts
- **Library view** — grid of saved fasteners with rename/download/delete

### `app.js`
Vanilla JavaScript handling:
- Chat message send/receive via fetch API
- Image upload (both landing page and in-chat)
- Library management (localStorage-backed)
- Theme toggle (light/dark)
- SVG preview rendering with cache-busting

### `styles.css`
CSS variables for theming, responsive layout, landing page gradients, and all component styles.

## Testing

Pytest suite in `tests/` covering:
- Parser correctness (dimensions, drives, typos, realism checks)
- Head/drive/shaft geometry validation
- Full assembly builds
- Thread gallery generation

## Output Convention

All generated files are written to `out/web/` with descriptive stems:
```
screw_pan_phillips_d5_00_l25_00_th.step
screw_pan_phillips_d5_00_l25_00_th.stl
screw_pan_phillips_d5_00_l25_00_th.svg
screw_pan_phillips_d5_00_l25_00_th_drawing.pdf
screw_pan_phillips_d5_00_l25_00_th_bundle.zip
```
