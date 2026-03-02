# Fastener Generator

Parametric CAD fastener generator with a chat-based web UI.

It builds screws/bolts (and matching nuts), then exports:
- STEP
- STL
- Preview SVG
- Engineering drawing PDF
- ZIP bundle

## What It Supports

### Fasteners
- Head types: `flat`, `pan`, `button`, `hex`
- Drive types: `hex`, `phillips`, `torx`, or `no drive`
- Fastener type: `screw` or `bolt`
  - screw: pointed tip allowed
  - bolt: flat end enforced

### Threads
- Thread pitch/height inference when omitted
- Single threaded length or multi-span threading
  - example: `thread 3-9 and 14-20`

### Matching Nut Flow
- After generation, chat asks:
  - `Do you want a matching nut?`
  - `What style for the matching nut?`
- Nut styles: `hex` or `square`
- Generates matching nut exports (STEP/STL/PDF/ZIP)

### Drawings
- Main fastener engineering drawing PDF (top/side/isometric + dimensions)
- Matching nut drawing PDF (aligned top/side views + key dimensions)

## Quick Start

### 1) Create environment
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

### 2) Run web app
```powershell
.\.venv\Scripts\python -m uvicorn screwgen.webapp:app --app-dir src --host 127.0.0.1 --port 8002
```

### 3) Open in browser
`http://127.0.0.1:8002`

## Usage Notes

- Free-text input is parsed for dimensions and options.
- If details are missing, the app asks follow-up questions.
- Option questions render as in-chat buttons (not manual typing).
- Unrealistic dimensions trigger a confirmation prompt.

Example prompt:
`pan head diameter 10 shank diameter 5 root diameter 4 length 30 pitch 1 thread length 18`

## Common Use Cases

- **Quick custom screw/bolt generation** from one plain-English prompt.
- **Interactive completion** when values are missing (buttons for screw/bolt, drive, confirmations).
- **Partial-thread designs** using explicit thread spans (e.g., `thread 3-9 and 14-20`).
- **Fastener realism checks** with suggestion + accept/reject flow.
- **Matching nut creation** for generated threaded fasteners.
- **Export-ready package** (STEP/STL/preview/drawing/ZIP) for downstream CAD work.

## Test Prompts

### 1) Full guided flow (buttons)
`pan head diameter 10 shank diameter 5 root diameter 4 length 30 pitch 1 thread height 0.5 thread length 18`

Expected:
- asks screw/bolt (buttons)
- asks drive (buttons)
- generates fastener files
- asks matching nut (Yes/No buttons)
- asks nut style (Hex/Square buttons)

### 2) Multi-span threading
`button screw head diameter 10 shank diameter 5 root diameter 4 length 30 pitch 1 thread height 0.5 thread 3-9 and 14-20 torx`

Expected:
- no screw/bolt prompt (explicit screw)
- no drive prompt (explicit torx)
- builds with multiple threaded regions
- matching nut flow appears after generation

### 3) Bolt + no-drive explicit
`flat bolt no drive head diameter 10 shank diameter 5 root diameter 4 length 30 pitch 1 thread height 0.5 thread length 18`

Expected:
- no screw/bolt prompt (explicit bolt)
- no drive prompt (explicit no drive)
- flat-ended bolt (no pointed tip)
- matching nut flow appears

### 4) Typo tolerance
`flat bold head diameter 10 shank diameter 5 root diameter 4 lenght 30 pitch 1 thread height 0.5 thread length 18`

Expected:
- `bold` interpreted as `bolt`
- `lenght` interpreted as `length`
- generation still succeeds

## Repository Structure

```text
src/screwgen/
  assembly.py
  cache.py
  drives.py
  export.py
  heads.py
  search_parser.py
  shaft.py
  spec.py
  threads.py
  webapp.py
  preview/
    ...

web/
  index.html
  app.js
  styles.css

tests/
  test_search_parser.py
  ...
```

## Testing

Run the suite:
```bash
pytest
```

Run just parser tests:
```bash
pytest tests/test_search_parser.py -q
```

## Output Location

Generated files are written under:
- `out/web/`

## Current Limitations

- Geometry is practical/preview oriented and not standards-certified.
- Some extreme combinations may trigger boolean fallbacks.

