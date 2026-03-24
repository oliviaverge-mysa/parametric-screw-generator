# Architecture

## Overview

The system generates parametric threaded fasteners from either a form-based builder interface or uploaded photos, then exports production-ready CAD files and engineering drawings. It consists of:

- **Python backend** (FastAPI + CadQuery) — geometry generation, image analysis, drawing export
- **Next.js frontend** (Vercel) — authenticated UI shell, API proxy to backend
- **Vanilla JS/CSS/HTML frontend** (`web/`) — the actual interactive UI loaded inside the Next.js shell

```
                    ┌─────────────────────────────┐
                    │      Vercel (Next.js)        │
                    │  ┌───────────────────────┐   │
                    │  │  Google OAuth          │   │
                    │  │  (@getmysa.com only)   │   │
                    │  └───────────────────────┘   │
                    │  ┌───────────────────────┐   │
  Browser ────────▶ │  │  page.tsx (app shell)  │   │
                    │  │  + app.js / styles.css │   │
                    │  └───────────────────────┘   │
                    │  ┌───────────────────────┐   │
                    │  │  API proxy routes      │   │
                    │  │  /api/chats/* ──────────┼───┼──▶  Railway (FastAPI)
                    │  │  /downloads/* ──────────┼───┼──▶  port 8000
                    │  └───────────────────────┘   │
                    └─────────────────────────────┘
```

## Project Structure

```
parametric-screw-generator/
├── src/screwgen/           # Python package
│   ├── spec.py             # Data models (ScrewSpec, HeadSpec, DriveSpec, ShaftSpec)
│   ├── search_parser.py    # Natural language → ScrewSpec parser
│   ├── heads.py            # Head geometry (flat, pan, button, hex)
│   ├── drives.py           # Drive recess geometry (hex, phillips, torx, square)
│   ├── shaft.py            # Shaft + tip geometry
│   ├── threads.py          # External helical thread application
│   ├── assembly.py         # Assembles head + drive + shaft + threads
│   ├── cache.py            # LRU shape cache
│   ├── export.py           # STEP/STL export helpers
│   ├── webapp.py           # FastAPI app (~3,200 lines): API, chat state machine,
│   │                       #   image detection, drawing generation, nut generation
│   └── preview/            # CLI scripts for preview galleries
│
├── web/                    # Canonical frontend source
│   ├── index.html          # HTML structure (landing, sidebar, builder, upload, library)
│   ├── app.js              # All UI logic (~1,940 lines)
│   ├── styles.css          # All styling and theming
│   └── brand-bg.png        # Background image
│
├── frontend/               # Next.js wrapper (deployed to Vercel)
│   ├── app/
│   │   ├── layout.tsx      # SessionProvider, metadata
│   │   ├── page.tsx        # Main page (embeds web/index.html structure as JSX)
│   │   ├── globals.css
│   │   ├── signin/page.tsx # Google sign-in page
│   │   ├── api/
│   │   │   ├── auth/[...nextauth]/route.ts  # NextAuth handlers
│   │   │   └── chats/
│   │   │       ├── route.ts                 # GET/POST/DELETE /api/chats
│   │   │       └── [...path]/route.ts       # All /api/chats/* (forwards X-Author-Name)
│   │   ├── downloads/[...path]/route.ts     # Proxy to backend /downloads/*
│   │   └── brand-bg/route.ts                # Serves brand-bg.png
│   ├── lib/backend.ts      # proxyToBackend() helper
│   ├── auth.ts             # NextAuth config (Google, @getmysa.com restriction)
│   ├── middleware.ts        # Auth guard for all routes
│   └── public/assets/      # Copies of app.js, styles.css, brand-bg.png
│
├── tests/                  # Pytest suite
├── out/web/                # Generated output files
├── run_web.py              # Uvicorn entry point
├── Dockerfile              # Python 3.11 slim + CadQuery
├── docker-compose.yml      # Single service, port 8000
├── railway.json            # Railway deployment config
├── pyproject.toml          # Python package metadata
├── .env.example            # Backend env vars
└── frontend/.env.example   # Frontend env vars
```

## Frontend Views & Navigation

The UI is a single-page app with four views managed by `setActiveView()` in `app.js`:

| View | DOM ID | Purpose |
|------|--------|---------|
| **Landing** | `#landing` | Full-screen overlay with "Build Your Own" and "Upload Photo" buttons |
| **Builder** | `#builder-view` | Form-based fastener specification → generate → preview |
| **Upload Photo** | `#upload-view` | Drag-and-drop image upload → auto-generate fastener |
| **Library** | `#library-view` | Grid of all saved fasteners with rename/download/delete |

Navigation flow:
- **Landing** → "Build Your Own" opens Builder view; "Upload Photo" opens Upload view
- **Sidebar toggle** (top of sidebar) switches between Builder and Upload Photo
- **Recent Fasteners** in sidebar shows last 1–2 items; "View Full Library" opens Library view
- **Brand logo** in header returns to Landing

### Sidebar Structure

1. **View nav** — Builder | Upload Photo toggle buttons
2. **Recent Fasteners** — thumbnail grid of latest generated items
3. **Builder form** (`#sidebar-builder-form`) — shown only in Builder view; scrollable with all spec fields

### Builder Form

**Fields and sections** (in sidebar order):
- Fastener Type: Screw / Bolt
- Head Type: Flat / Pan / Button / Hex
- Drive Type: Phillips / Torx / Square / Hex / No Drive
- Slotted: Yes / No (hidden if drive = "no drive")
- Threaded: Yes / No
- Matching Nut: Yes / No → Nut Style: Hex / Square (shown if yes)
- ISO Designation: text input (e.g. `M8`, `M5x0.8x20`) — auto-fills dimensions
- Dimensions (mm): Head Diameter, Head Height, Shank Diameter, Root Diameter, Length (shaft length: bottom of head to tip), Tip Length, Pitch, Thread Regions (e.g. `3-5, 9-14`)

**Minimum required to generate**: Head Diameter + Length. All other fields have smart defaults.

**Defaults**: head=pan, drive=no drive, fastener=screw, threaded=yes, matching nut=no, nut style=hex.

**Generate flow** (`handleBuilderGenerate`):
1. Builds a natural-language query string from the form state
2. Creates a new chat session (`POST /api/chats`)
3. Sends the query as a message (`POST /api/chats/{id}/messages`)
4. Polls the chat for results, auto-answering any pending questions using builder state
5. Displays preview cards in the main content area with download buttons

### Upload Photo Flow

1. User drops/browses an image file
2. Creates a new chat and uploads the image (`POST /api/chats/{id}/image`)
3. Backend runs CV pipeline to estimate fastener parameters
4. Auto-answers all follow-up questions with sensible defaults (screw, yes to generate, no slot, no nut)
5. Displays generated preview with download buttons

### Library

- Backed by `localStorage` (`fastener-library-cache-v1`) merged with server chat data
- Each entry shows: thumbnail, name (editable), download links, delete button
- Context menu for renaming

### Preview Display

- SVG previews from CadQuery use Y-up coordinates; browsers render SVG Y-down
- **Fix**: CSS `transform: scaleY(-1)` on all preview `<img>` elements (`.preview-img-colorized`, `.recent-thumb img`, `.library-media img`)

## Backend: Core Modules

### `spec.py` — Data Models

Immutable dataclasses defining the fastener specification:
- `ScrewSpec` — top-level container
- `HeadSpec` — head type, diameter `d`, height `h`, hex across-flats
- `DriveSpec` — drive type, size, depth, fit mode
- `ShaftSpec` — minor diameter `d_minor`, length `L`, tip length
- `ThreadRegionSpec` / `SmoothRegionSpec` — thread span definitions with start/end/pitch
- Length (`ShaftSpec.L`) means **shaft length** (bottom of head to tip), not overall length

### `search_parser.py` — Natural Language Parser

Converts free-text queries into `ScrewSpec` objects:
- Regex-based dimension extraction (diameter, length, pitch, head diameter, etc.)
- Typo normalization (`bold` → `bolt`, `lenght` → `length`)
- Interactive prompts for missing values (screw/bolt choice, drive type)
- Realism checks with confirmation flow
- `apply_realism_checks` flag allows image-derived specs to skip validation
- Thread region parsing: supports `thread 3-5, 9-14` syntax (0 = base of head)

### `heads.py` — Head Geometry

CadQuery solids for each head type:
- `flat` — countersunk cone (tapered)
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

Applies external helical threads to shaft geometry. Threads follow the tip cone downward for screws (threads are generated after the tip geometry so they wrap onto the tapered surface).

### `assembly.py` — Fastener Assembly

Combines head + drive + shaft + threads into a single CadQuery solid. Handles the full build pipeline including thread region application and slot cutting.

### `cache.py` — Shape Cache

LRU-cached wrappers around geometry builders to avoid redundant computation during gallery/preview generation.

### `export.py` — File Export

Helpers for writing STEP and STL files with consistent output paths.

## Backend: `webapp.py` (~3,200 lines)

### API Layer (FastAPI)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chats` | GET | List all chat sessions |
| `/api/chats` | POST | Create new chat |
| `/api/chats/{id}` | GET | Get chat with messages |
| `/api/chats/{id}` | DELETE | Delete chat |
| `/api/chats/{id}/messages` | POST | Send message (reads `X-Author-Name` header) |
| `/api/chats/{id}/image` | POST | Upload image (reads `X-Author-Name` header) |
| `/downloads/{path}` | GET | Serve generated files (STEP/STL/SVG/PDF/ZIP) |
| `/health` | GET | Health check for Railway |

### Chat State Machine (`ChatState`)

Tracks per-session state:
- `id`, `title`, `query`, `messages`, `answers`
- `pending_question` — current question awaiting user response
- `pending_flow` — which flow stage is active (e.g. `image_estimate_confirm`)
- `latest_files` — URLs of most recently generated files
- `latest_spec` — the `ScrewSpec` used for generation
- `author_name` — captured from `X-Author-Name` header, used in drawing title block

Multi-step flows: parse query → resolve ambiguities → generate geometry → offer matching nut.

### Image Detection Pipeline

Three estimation paths (tried in order of preference):

1. **`_vision_estimate`** — multimodal LLM (Gemini/Groq/OpenAI) analyzes the photo
2. **`_opencv_estimate`** — OpenCV contour analysis: profile shape, head ratio, drive detection via template correlation and contour metrics
3. **`_fallback_estimate`** — basic contour elongation heuristics

Detection features:
- Subject extraction via edge-based card detection
- Profile analysis: contour elongation, head ratio, head taper
- Drive detection: Hough line counting (horizontal/vertical/diagonal), template correlation (phillips/square/torx shapes), contour solidity, radial lobe analysis
- Post-classification overrides for common misclassification patterns (e.g. square vs phillips, bolt vs screw)
- Slotted detection: long straight lines spanning >55% of head width

Thread length defaults to `max_threadable` (shaft length minus tip length) for screws.

### Geometry Generation

`_build_from_spec(chat, spec)`:
1. Builds the 3D screw via `make_screw_from_spec` (assembly.py)
2. Exports STEP, STL, SVG preview
3. Generates engineering drawing PDF (or SVG fallback)
4. Creates ZIP bundle of all files
5. Returns result message with all download URLs

Preview SVG generation:
- Model rotated `(1, 0, 0), -70°` for angled view showing head and drive
- Projection direction `(0.10, -0.30, 1.0)` for catalog-style perspective

### Nut Generation

`_build_nut_from_params(chat, ...)`:
- Generates hex or square nut geometry from major diameter, pitch, and style
- CadQuery solid with internal thread via helical boolean subtraction
- Corner chamfers on hex nuts
- Separate SVG preview, STEP, STL, drawing PDF exports

## Engineering Drawing Generation

### Screw Drawing (`_write_engineering_drawing_pdf`)

**Page layout**: Landscape A4 with drafting frame (zone grid columns 1–6, rows A–E).

**Header**: Part name (e.g. "Pan Phillips/Slotted Threaded Bolt (3.5 x 16.0 mm)"), subtitle with head/drive/units.

**Side view** (left portion of drawing):

| Head type | Rendering |
|-----------|-----------|
| `flat` | Trapezoid (countersunk cone profile) |
| `pan` / `button` | Rectangle + dome arc on left edge (face of head). Arc uses sine curve, bulge = 18% of head width. |
| `hex` | Rectangle + three horizontal lines across head (across-flats indication) |

- Shank drawn as rectangle at **root diameter**
- Dashed lines at **major (shank) diameter** between body start and tip
- Screws: triangular pointed tip; Bolts: flat rectangular end
- Thread crests rendered as angled tick marks at regular pitch intervals within each thread region

**Top view** (right portion, positioned to clear diameter labels):

| Drive type | Shape |
|------------|-------|
| Phillips | Two crossing rectangles (cross shape) |
| Torx | Six lobes — outer/inner circle vertices connected |
| Square (Robertson) | Diamond (square rotated 45°, corners pointing up/down/left/right) |
| Hex socket | Regular hexagon |
| Slot | Horizontal rectangle spanning ~94% of head diameter |

- Head outline: circle (or hexagon for hex heads)
- Dashed centerline cross extending ~15% beyond head

**Dimension layout** (all dimensions in mm):

| Dimension | Position |
|-----------|----------|
| Thread length | Above the side view, close to the body |
| Head height | Below the side view, inline with shaft length |
| Shaft length | Below the side view, same row as head height |
| Overall length | One row further below shaft length |
| Tip length | Below view, near the tip (screws only) |
| Ø major diameter | Vertical dim line right of tip, label centered above top arrow |
| Ø root diameter | Second vertical dim line right of major, label above top arrow |
| Ø head diameter | Vertical dim line right of top view circle |

Top view position is computed to clear the root diameter label text (`root_label_right + top_r + 12`), then shifted further right by 80% of available space.

**Isometric view** (bottom-left):
- Embedded from the SVG preview file via `svg2rlg` + ReportLab `renderPDF`
- **Critical**: must apply `c.translate(cx, cy + rendered_h); c.scale(scale, -scale)` to flip SVG Y-down into PDF Y-up coordinates

**Title block** (bottom-right, 285×108pt):

| Cell | Content |
|------|---------|
| DRAWN BY | Signed-in user's name (from `X-Author-Name` header via Next.js proxy → `chat.author_name`) |
| APPROVED BY | Empty |
| DATE | Current date (YYYY-MM-DD) |
| UNITS | mm |
| HEAD / DRIVE | e.g. "Pan/Square" |
| SCALE | NTS |

**Spec text** (bottom-left): Major Ø, Root Ø, Head H, Pitch, thread count.

### Nut Drawing (`_write_nut_drawing_pdf`)

- Top view: hexagon or square outline with inner bore circle
- Side view: chamfered profile with dashed bore lines
- Dimensions: across flats, bore diameter, thickness
- Same MYSA title block format (DRAWN BY from `author_name`, APPROVED BY empty)

### Drawing Coordinate System Notes

- **ReportLab PDF canvas**: Y increases **upward** (origin at bottom-left)
- **CadQuery SVG export**: Y increases **downward**
- **Browser SVG rendering**: Y increases **downward**
- When embedding SVG into PDF: apply negative Y scale to flip
- When displaying SVG in browser: apply CSS `transform: scaleY(-1)` to flip

## Deployment

### Architecture

| Component | Platform | Config |
|-----------|----------|--------|
| Frontend | **Vercel** | Next.js App Router, root `frontend/` |
| Backend | **Railway** | Docker container, `Dockerfile` + `railway.json` |
| Auth | **Google OAuth** | NextAuth v5, restricted to `@getmysa.com` |

### API Proxy (`frontend/lib/backend.ts`)

All frontend API calls go through Next.js API routes that proxy to the backend:

```
Browser → /api/chats/* → proxyToBackend() → Railway:8000/api/chats/*
Browser → /downloads/* → proxyToBackend() → Railway:8000/downloads/*
```

`proxyToBackend()`:
- Adds `Authorization: Bearer <key>` if `BACKEND_API_KEY` is set
- Adds `X-Author-Name` header (from NextAuth session) on POST requests to `/api/chats/*`
- Passes through response headers: `content-type`, `content-disposition`, `content-length`, `cache-control`
- Returns 502 JSON on backend connection failure

### Environment Variables

**Backend** (`.env.example`):

| Variable | Purpose | Default |
|----------|---------|---------|
| `GEMINI_API_KEY` | Google Gemini vision API key | (none, optional) |
| `GEMINI_VISION_MODEL` | Gemini model name | `gemini-2.0-flash` |
| `GROQ_API_KEY` | Groq vision API key | (none, optional) |
| `GROQ_VISION_MODEL` | Groq model name | `meta-llama/llama-4-scout-17b-16e-instruct` |
| `OPENAI_API_KEY` | OpenAI vision API key | (none, optional) |
| `OPENAI_VISION_MODEL` | OpenAI model name | `gpt-4o` |
| `OPENAI_BASE_URL` | OpenAI API base URL | `https://api.openai.com/v1` |
| `DRAWING_AUTHOR` | Fallback author name for drawings | `User` |
| `BACKEND_API_KEY` | Bearer token for API protection | (none, no auth) |
| `HOST` | Server bind address | `127.0.0.1` |
| `PORT` | Server port | `8000` |

**Frontend** (`frontend/.env.example`):

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `AUTH_SECRET` | NextAuth session encryption key |
| `AUTH_TRUST_HOST` | Set `true` for production |
| `BACKEND_URL` | Backend URL (e.g. Railway deployment URL) |
| `BACKEND_API_KEY` | Must match backend's `BACKEND_API_KEY` |

### Local Development

```bash
# Terminal 1: Backend
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -e ".[dev]"
python run_web.py            # → http://localhost:8000

# Terminal 2: Frontend (optional, for auth flow)
cd frontend
npm install
npx next dev --port 3000     # → http://localhost:3000
```

The backend serves the vanilla frontend directly at port 8000 (no auth). The Next.js frontend at port 3000 adds Google OAuth and proxies API calls to port 8000.

## Output Files

All generated files are written to `out/web/` with descriptive stems:

```
screw_pan_phillips_d5_00_l25_00_th.step        # STEP CAD model
screw_pan_phillips_d5_00_l25_00_th.stl         # STL mesh
screw_pan_phillips_d5_00_l25_00_th.svg         # Shaded SVG preview
screw_pan_phillips_d5_00_l25_00_th_drawing.pdf # Engineering drawing
screw_pan_phillips_d5_00_l25_00_th_bundle.zip  # All of the above
```

Nut files follow the same pattern with `nut_` prefix.

## Testing

Pytest suite in `tests/` covering:
- Parser correctness (dimensions, drives, typos, realism checks)
- Head/drive/shaft geometry validation
- Full assembly builds
- Thread gallery generation

```bash
pytest
```

## Limitations

- Geometry is practical/preview-oriented, not standards-certified
- Image detection works best with single-fastener photos on clean backgrounds
- Some extreme parameter combinations may trigger boolean fallbacks in the CAD kernel
- CadQuery is memory-heavy; not suitable for free serverless platforms
