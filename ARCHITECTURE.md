# Fastener Generator Architecture

## Purpose
Generate parametric fasteners from plain text and interactive chat prompts, then export:
- STEP
- STL
- Preview SVG
- Engineering drawing PDF
- ZIP bundle (all files)

The system supports:
- screw/bolt mode selection
- head + drive + shaft modeling
- single or multi-region external threads
- matching nut generation (hex/square)

## High-Level Flow
1. User sends plain-text request in web chat.
2. Parser extracts dimensions/features from text.
3. Missing values are requested interactively.
4. Realism checks can ask confirmation (Yes/No).
5. Spec is assembled and converted into CAD geometry.
6. Exports are generated and attached to the result message.
7. Optional follow-up generates a matching nut.

## Core Modules
- `src/screwgen/search_parser.py`
  - Text parsing, typo normalization, inference defaults, realism prompts.
  - Detects `screw` vs `bolt`, head type, drive, dimensions, and thread regions.
- `src/screwgen/spec.py`
  - Immutable data model (`ScrewSpec`, head/drive/shaft/regions).
- `src/screwgen/heads.py`
  - Head solids (`flat`, `pan`, `button`, `hex`).
- `src/screwgen/drives.py`
  - Drive cut solids (`hex`, `phillips`, `torx`).
- `src/screwgen/shaft.py`
  - Shaft generation:
    - `pointed` (screw)
    - `flat` (bolt)
- `src/screwgen/threads.py`
  - External helical thread application on shaft-local +Z solids.
- `src/screwgen/assembly.py`
  - Builds the final fastener from spec and applies all thread regions.
- `src/screwgen/webapp.py`
  - FastAPI app + chat state machine + export pipeline + drawing generation.
  - Matching-nut flow and nut CAD generation.

## Interaction Model (Web Chat)
### Prompt Types
- Screw/Bolt choice prompt (buttons)
- Drive type prompt (buttons)
- Yes/No confirmations (buttons)
- Matching nut offer (buttons)
- Matching nut style (`hex`/`square`) prompt (buttons)

### Chat State
`ChatState` tracks:
- `query`, `messages`
- `pending_question`, `answers`
- `pending_flow` (multi-step post-generation flows)
- `latest_spec`, `latest_files`

## Geometry Rules
### Fastener Type
- `screw`: shaft tip may be pointed.
- `bolt`: shaft end is flat (`tip_len = 0` enforced).

### Thread Regions
- Supports multiple thread spans (e.g., `3-9` and `14-20`).
- Assembly applies thread geometry region-by-region in sequence.

### Matching Nut
- Generated from latest threaded fastener.
- Styles: `hex` or `square`.
- Internal thread is produced by subtracting a threaded tap solid.
- Falls back to a clearance bore only if helical boolean fails.

## Drawing Generation
- Main fastener drawing:
  - side view, top view, dimensions, title block, isometric.
- Nut drawing:
  - aligned top/side views, dimensions, thread metadata.

## Export Conventions
Files are written to `out/web/` with descriptive stems:
- `<stem>.step`
- `<stem>.stl`
- `<stem>.svg`
- `<stem>_drawing.pdf`
- `<stem>_bundle.zip`

## Current Constraints
- Geometry is practical/preview-oriented (not standards-certified).
- Some extreme parameter combinations can still trigger boolean fallback behavior.

