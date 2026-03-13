# Fastener Generator

Parametric CAD fastener generator with a chat-based web UI. Describe what you need in plain English (or upload a photo), and the app generates production-ready CAD files.

## Features

- **Natural language input** — type something like `flat head phillips screw M5x30` and get a fully modeled fastener
- **Image detection** — upload a photo of a real screw/bolt and the app identifies type, head, drive, and approximate dimensions using computer vision
- **Export formats** — STEP, STL, preview SVG, engineering drawing PDF, and a ZIP bundle containing everything
- **Matching nut generation** — after creating a fastener, optionally generate a matching hex or square nut
- **Fastener library** — save, rename, and manage generated fasteners in a persistent sidebar library

### Supported Fastener Options

| Category | Options |
|----------|---------|
| Fastener type | `screw` (pointed tip), `bolt` (flat end) |
| Head types | `flat`, `pan`, `button`, `hex` |
| Drive types | `hex`, `phillips`, `torx`, `square`, `no drive` |
| Threading | Single span or multi-region (e.g. `thread 3-9 and 14-20`) |
| Nut styles | `hex`, `square` |

## Quick Start

### Option A — Docker (recommended)

```bash
docker compose up --build
```

Open `http://localhost:8000`. That's it.

### Option B — Local install

```bash
# 1. Create environment (requires Python 3.11+)
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
.\.venv\Scripts\activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Run
python run_web.py
```

Open `http://127.0.0.1:8000`.

### Configuration (optional)

Copy `.env.example` to `.env` and fill in any values you want:

```bash
cp .env.example .env
```

All environment variables are optional — the app works without any of them. See `.env.example` for the full list.

## How It Works

1. Enter a plain-text description in the chat (e.g. `pan head phillips screw diameter 5 length 25`)
2. The parser extracts dimensions, head type, drive type, and fastener type
3. Missing values are requested via interactive button prompts
4. Unrealistic dimensions trigger a confirmation prompt
5. CadQuery builds the 3D geometry and exports all file formats
6. After generation, the app offers to create a matching nut

You can also upload an image of a real fastener — the CV pipeline isolates the subject, analyzes the profile, and estimates the parameters.

## Testing

```bash
pytest
```

## Project Structure

```
src/screwgen/
  spec.py            Data models (ScrewSpec, HeadSpec, DriveSpec, ShaftSpec)
  search_parser.py   Natural language → ScrewSpec parser
  heads.py           Head geometry (flat, pan, button, hex)
  drives.py          Drive recess geometry (hex, phillips, torx, square)
  shaft.py           Shaft + tip geometry
  threads.py         External helical thread application
  assembly.py        Assembles head + drive + shaft + threads into a fastener
  cache.py           LRU shape cache for repeated builds
  export.py          STEP/STL export helpers
  webapp.py          FastAPI app, chat state machine, image detection, drawings
  preview/           CLI scripts for generating preview galleries

web/
  index.html         Landing page + chat UI + library view
  app.js             Frontend logic (chat, library, theme, image upload)
  styles.css         All styling and theming

tests/               Pytest suite covering parser, geometry, and assembly
```

## Output

Generated files are written to `out/web/` with descriptive filenames:
- `<stem>.step` / `<stem>.stl` — CAD models
- `<stem>.svg` — shaded preview
- `<stem>_drawing.pdf` — engineering drawing
- `<stem>_bundle.zip` — all of the above

## Deployment

### Docker on an internal server (recommended)

The easiest way to make this available to your team:

```bash
# On your server
git clone https://github.com/oliviaverge-mysa/parametric-screw-generator.git
cd parametric-screw-generator
cp .env.example .env        # edit if needed
docker compose up -d --build
```

Everyone on the network can then access it at `http://server-ip:8000`.

### Cloud VM

If you don't have an internal server, spin up a free-tier VM (AWS EC2 `t2.micro`, GCP `e2-micro`, or Azure `B1s`), install Docker, and follow the steps above. CadQuery is too memory-heavy for free serverless platforms like Heroku or Render.

## Limitations

- Geometry is practical/preview-oriented, not standards-certified
- Image detection works best with single-fastener photos on clean backgrounds
- Some extreme parameter combinations may trigger boolean fallbacks in the CAD kernel
