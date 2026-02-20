"""Local chat-style web app for interactive screw generation."""

from __future__ import annotations

import itertools
import math
import re
import time
import zipfile
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .search_parser import parse_query, screw_spec_from_query
from .spec import ThreadRegionSpec


class _NeedInput(Exception):
    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


@dataclass
class ChatState:
    id: int
    title: str
    query: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    pending_question: str | None = None
    latest_files: dict[str, str] = field(default_factory=dict)


class MessageIn(BaseModel):
    content: str


class EditMessageIn(BaseModel):
    content: str


class RenameChatIn(BaseModel):
    title: str


class ChatSummary(BaseModel):
    id: int
    title: str


_ROOT = Path(__file__).resolve().parents[2]
_WEB_DIR = _ROOT / "web"
_DOWNLOAD_DIR = _ROOT / "out" / "web"
_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ScrewGen Chat")
app.mount("/assets", StaticFiles(directory=_WEB_DIR), name="assets")
app.mount("/downloads", StaticFiles(directory=_DOWNLOAD_DIR), name="downloads")

_chat_counter = itertools.count(1)
_chats: dict[int, ChatState] = {}


def _new_chat(title: str | None = None) -> ChatState:
    cid = next(_chat_counter)
    chat = ChatState(id=cid, title=title or "New Screw")
    _chats[cid] = chat
    return chat


def _bot(chat: ChatState, content: str, kind: str = "text", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    msg = {"role": "bot", "content": content, "kind": kind}
    if extra:
        msg.update(extra)
    chat.messages.append(msg)
    return msg


def _user(chat: ChatState, content: str) -> dict[str, Any]:
    msg = {"role": "user", "content": content, "kind": "text"}
    chat.messages.append(msg)
    return msg


def _write_engineering_drawing_svg(spec, output_path: Path) -> None:
    head_d = spec.head.d
    head_h = spec.head.h
    shaft_d = spec.regions[0].major_d if spec.regions and isinstance(spec.regions[0], ThreadRegionSpec) else None
    if shaft_d is None:
        # Best available major diameter approximation for labels.
        shaft_d = max(spec.shaft.d_minor * 1.18, spec.shaft.d_minor + 0.4)
    length = spec.shaft.L
    tip_len = spec.shaft.tip_len
    drive = spec.drive.type if spec.drive is not None else "none"
    threaded_len = 0.0
    pitch = None
    for region in spec.regions:
        if isinstance(region, ThreadRegionSpec):
            threaded_len += region.length
            pitch = region.pitch

    # Layout in SVG user units.
    W, H = 1000, 620
    side_x, side_y = 110, 150
    side_len = 560
    px_per_mm = side_len / max(length, 1.0)
    shank_r = 0.5 * shaft_d * px_per_mm
    head_r = 0.5 * head_d * px_per_mm
    head_px = max(head_h * px_per_mm, 30)
    tip_px = max(tip_len * px_per_mm, 20)
    shank_px = max((length - tip_len) * px_per_mm, 40)
    top_cx, top_cy = 760, 200
    top_r = max(0.5 * head_d * px_per_mm, 35)

    def esc(v: str) -> str:
        return (
            v.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    drive_glyph = ""
    if drive == "phillips":
        drive_glyph = (
            f'<line x1="{top_cx - top_r*0.45:.1f}" y1="{top_cy:.1f}" x2="{top_cx + top_r*0.45:.1f}" y2="{top_cy:.1f}" class="ink"/>'
            f'<line x1="{top_cx:.1f}" y1="{top_cy - top_r*0.45:.1f}" x2="{top_cx:.1f}" y2="{top_cy + top_r*0.45:.1f}" class="ink"/>'
        )
    elif drive == "torx":
        drive_glyph = (
            f'<circle cx="{top_cx:.1f}" cy="{top_cy:.1f}" r="{top_r*0.28:.1f}" class="ink" fill="none"/>'
            f'<circle cx="{top_cx:.1f}" cy="{top_cy:.1f}" r="{top_r*0.17:.1f}" class="ink" fill="none"/>'
        )
    elif drive == "hex":
        pts = []
        r = top_r * 0.28
        for k in range(6):
            a = 0.523599 + k * 1.047198
            x = top_cx + r * __import__("math").cos(a)
            y = top_cy + r * __import__("math").sin(a)
            pts.append(f"{x:.1f},{y:.1f}")
        drive_glyph = f'<polygon points="{" ".join(pts)}" class="ink" fill="none"/>'

    thread_lines = []
    if threaded_len > 0:
        pitch_val = pitch if pitch and pitch > 0 else max(0.8, 0.25 * shaft_d)
        count = max(3, int(threaded_len / pitch_val))
        span = min(threaded_len, length - tip_len) * px_per_mm
        x0 = side_x + head_px
        for i in range(count):
            x = x0 + (i + 1) * span / (count + 1)
            thread_lines.append(
                f'<line x1="{x:.1f}" y1="{side_y - shank_r:.1f}" x2="{x:.1f}" y2="{side_y + shank_r:.1f}" class="thread"/>'
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <style>
    .bg {{ fill: #ffffff; }}
    .ink {{ stroke: #222; stroke-width: 2; fill: none; }}
    .dim {{ stroke: #666; stroke-width: 1.2; fill: none; }}
    .thread {{ stroke: #444; stroke-width: 1; }}
    .txt {{ fill: #222; font-family: Arial, sans-serif; font-size: 18px; }}
    .small {{ fill: #222; font-family: Arial, sans-serif; font-size: 14px; }}
    .title {{ fill: #111; font-family: Arial, sans-serif; font-size: 24px; font-weight: 600; }}
  </style>
  <rect class="bg" x="0" y="0" width="{W}" height="{H}"/>

  <text x="40" y="42" class="title">Screw Engineering Drawing</text>
  <text x="40" y="70" class="small">Type: {esc(spec.head.type)} | Drive: {esc(drive)} | Generated by ScrewGen</text>

  <!-- Side view -->
  <rect x="{side_x:.1f}" y="{side_y-head_r:.1f}" width="{head_px:.1f}" height="{2*head_r:.1f}" class="ink"/>
  <rect x="{side_x+head_px:.1f}" y="{side_y-shank_r:.1f}" width="{shank_px:.1f}" height="{2*shank_r:.1f}" class="ink"/>
  <polygon points="{side_x+head_px+shank_px:.1f},{side_y-shank_r:.1f} {side_x+head_px+shank_px+tip_px:.1f},{side_y:.1f} {side_x+head_px+shank_px:.1f},{side_y+shank_r:.1f}" class="ink"/>
  {''.join(thread_lines)}

  <!-- Top/head view -->
  <circle cx="{top_cx:.1f}" cy="{top_cy:.1f}" r="{top_r:.1f}" class="ink"/>
  {drive_glyph}

  <!-- Dimensions -->
  <line x1="{side_x:.1f}" y1="{side_y+130:.1f}" x2="{side_x+head_px+shank_px+tip_px:.1f}" y2="{side_y+130:.1f}" class="dim"/>
  <line x1="{side_x:.1f}" y1="{side_y+120:.1f}" x2="{side_x:.1f}" y2="{side_y+140:.1f}" class="dim"/>
  <line x1="{side_x+head_px+shank_px+tip_px:.1f}" y1="{side_y+120:.1f}" x2="{side_x+head_px+shank_px+tip_px:.1f}" y2="{side_y+140:.1f}" class="dim"/>
  <text x="{side_x+180:.1f}" y="{side_y+122:.1f}" class="txt">L = {length:.2f}</text>

  <line x1="{side_x+head_px+40:.1f}" y1="{side_y-90:.1f}" x2="{side_x+head_px+40+min(threaded_len,length):.1f}" y2="{side_y-90:.1f}" class="dim"/>
  <text x="{side_x+head_px+44:.1f}" y="{side_y-96:.1f}" class="small">Threaded = {threaded_len:.2f}</text>

  <text x="{top_cx+top_r+20:.1f}" y="{top_cy-10:.1f}" class="txt">Head Ø = {head_d:.2f}</text>
  <text x="{top_cx+top_r+20:.1f}" y="{top_cy+18:.1f}" class="txt">Shank Ø = {shaft_d:.2f}</text>
  <text x="{top_cx+top_r+20:.1f}" y="{top_cy+46:.1f}" class="txt">Tip = {tip_len:.2f}</text>
  <text x="40" y="{H-36}" class="small">Pitch = {pitch if pitch is not None else 0:.3f} | Units follow your input context.</text>
</svg>"""
    output_path.write_text(svg, encoding="utf-8")


def _write_engineering_drawing_pdf(
    spec,
    output_path: Path,
    screw_name: str,
    author_name: str | None = None,
) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    author = (author_name or Path.home().name or "User").strip() or "User"
    screw_label = (screw_name or f"{spec.head.type.title()} Screw").strip()

    head_d = float(spec.head.d)
    head_h = float(spec.head.h)
    root_d = float(spec.shaft.d_minor)
    length = float(spec.shaft.L)
    tip_len = float(spec.shaft.tip_len)
    drive = spec.drive.type if spec.drive is not None else "none"
    shaft_d = None
    threaded_len = 0.0
    pitch_values: list[float] = []
    total_threads = 0.0
    region_ranges: list[tuple[str, float, float, float | None]] = []
    cursor = 0.0
    for region in spec.regions:
        if isinstance(region, ThreadRegionSpec):
            region_major = float(region.major_d) if region.major_d is not None else None
            region_pitch = float(region.pitch)
            region_len = float(region.length)
            if shaft_d is None and region_major is not None:
                shaft_d = region_major
            threaded_len += region_len
            pitch_values.append(region_pitch)
            starts = max(1, int(region.starts))
            total_threads += (region_len / region_pitch) * starts
            region_ranges.append(("thread", cursor, cursor + region_len, region_pitch))
            cursor += region_len
        else:
            region_len = float(region.length)
            region_ranges.append(("smooth", cursor, cursor + region_len, None))
            cursor += region_len
    if shaft_d is None:
        shaft_d = max(root_d * 1.18, root_d + 0.4)

    avg_pitch = (sum(pitch_values) / len(pitch_values)) if pitch_values else None

    page_w, page_h = A4
    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle(f"{screw_label} Drawing")

    def _dim_h(x1: float, x2: float, y: float, ext_y: float, label: str) -> None:
        c.line(x1, ext_y, x1, y)
        c.line(x2, ext_y, x2, y)
        c.line(x1, y, x2, y)
        ah = 5
        c.line(x1, y, x1 + ah, y + 1.8)
        c.line(x1, y, x1 + ah, y - 1.8)
        c.line(x2, y, x2 - ah, y + 1.8)
        c.line(x2, y, x2 - ah, y - 1.8)
        c.setFont("Helvetica", 9)
        c.drawCentredString((x1 + x2) * 0.5, y + 6, label)

    def _dim_v(x: float, y1: float, y2: float, ext_x: float, label: str) -> None:
        c.line(ext_x, y1, x, y1)
        c.line(ext_x, y2, x, y2)
        c.line(x, y1, x, y2)
        ah = 5
        c.line(x, y1, x + 1.8, y1 + ah)
        c.line(x, y1, x - 1.8, y1 + ah)
        c.line(x, y2, x + 1.8, y2 - ah)
        c.line(x, y2, x - 1.8, y2 - ah)
        c.setFont("Helvetica", 9)
        c.drawString(x + 6, (y1 + y2) * 0.5 - 2, label)

    # Header
    c.setFont("Helvetica-Bold", 15)
    c.drawString(30, page_h - 32, "Engineering Drawing")
    c.setFont("Helvetica", 10)
    c.drawString(30, page_h - 47, f"Screw: {screw_label}")
    c.drawString(30, page_h - 61, f"Head: {spec.head.type.title()} | Drive: {drive.title()} | Units: mm")

    # Side view geometry block
    side_x = 60
    side_y = page_h - 210
    side_len = 390
    px_per_mm = side_len / max(length, 1e-6)
    shank_r = 0.5 * shaft_d * px_per_mm
    head_r = 0.5 * head_d * px_per_mm
    root_r = 0.5 * root_d * px_per_mm
    head_px = max(head_h * px_per_mm, 18)
    tip_px = max(tip_len * px_per_mm, 12)
    body_px = max((length - tip_len) * px_per_mm, 22)
    x_body0 = side_x + head_px
    x_tip0 = x_body0 + body_px

    # Head and shaft
    c.rect(side_x, side_y - head_r, head_px, 2 * head_r, stroke=1, fill=0)
    c.rect(x_body0, side_y - root_r, body_px, 2 * root_r, stroke=1, fill=0)
    # Tip cone
    c.line(x_tip0, side_y - root_r, x_tip0 + tip_px, side_y)
    c.line(x_tip0 + tip_px, side_y, x_tip0, side_y + root_r)
    c.line(x_tip0, side_y + root_r, x_tip0, side_y - root_r)

    # Crest envelope
    c.setDash([3, 2], 0)
    c.line(x_body0, side_y - shank_r, x_tip0, side_y - shank_r)
    c.line(x_body0, side_y + shank_r, x_tip0, side_y + shank_r)
    c.setDash([], 0)

    # Thread rendering by region spans
    for kind, start_mm, end_mm, p in region_ranges:
        if kind != "thread":
            continue
        start_x = x_body0 + start_mm * px_per_mm
        end_x = x_body0 + min(end_mm, length - tip_len) * px_per_mm
        pitch_here = p if p is not None and p > 0 else max(0.8, 0.25 * shaft_d)
        crest_count = max(2, int((end_mm - start_mm) / pitch_here))
        for i in range(crest_count):
            x = start_x + (i + 0.5) * (end_x - start_x) / crest_count
            c.setLineWidth(0.7)
            c.line(x - 2.2, side_y - shank_r, x + 2.2, side_y - root_r)
            c.line(x - 2.2, side_y + shank_r, x + 2.2, side_y + root_r)
        c.setLineWidth(1)

    # Top/head view
    top_cx, top_cy = 510, page_h - 185
    top_r = max(0.5 * head_d * px_per_mm, 20)
    c.circle(top_cx, top_cy, top_r, stroke=1, fill=0)
    if drive == "phillips":
        c.line(top_cx - top_r * 0.45, top_cy, top_cx + top_r * 0.45, top_cy)
        c.line(top_cx, top_cy - top_r * 0.45, top_cx, top_cy + top_r * 0.45)
    elif drive == "torx":
        c.circle(top_cx, top_cy, top_r * 0.28, stroke=1, fill=0)
        c.circle(top_cx, top_cy, top_r * 0.17, stroke=1, fill=0)
    elif drive == "hex":
        r = top_r * 0.28
        pts = []
        for k in range(6):
            a = 0.523599 + k * 1.047198
            pts.append((top_cx + r * math.cos(a), top_cy + r * math.sin(a)))
        for i in range(6):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 6]
            c.line(x1, y1, x2, y2)

    # Dim lines and labels
    c.setFont("Helvetica-Bold", 10)
    c.drawString(side_x, side_y + head_r + 22, "SIDE VIEW")
    c.drawString(top_cx - 30, top_cy + top_r + 20, "TOP VIEW")

    _dim_h(side_x, x_tip0 + tip_px, side_y - head_r - 34, side_y - head_r, f"Full Length L = {length:.2f}")
    _dim_h(side_x, x_body0, side_y - head_r - 52, side_y - head_r, f"Head Height = {head_h:.2f}")
    _dim_h(x_tip0, x_tip0 + tip_px, side_y - root_r - 18, side_y - root_r, f"Tip Length = {tip_len:.2f}")
    _dim_h(x_body0, x_body0 + threaded_len * px_per_mm, side_y + shank_r + 24, side_y + shank_r, f"Threaded Length = {threaded_len:.2f}")
    _dim_v(x_tip0 + tip_px + 36, side_y - shank_r, side_y + shank_r, x_tip0 + tip_px, f"Major Dia = {shaft_d:.2f}")
    _dim_v(x_tip0 + tip_px + 70, side_y - root_r, side_y + root_r, x_tip0 + tip_px, f"Root Dia = {root_d:.2f}")
    _dim_v(top_cx + top_r + 42, top_cy - top_r, top_cy + top_r, top_cx + top_r, f"Head Dia = {head_d:.2f}")

    c.setFont("Helvetica", 9)
    spec_y = page_h - 370
    c.drawString(56, spec_y, f"Shank/Shaft Diameter: {shaft_d:.2f} mm")
    c.drawString(56, spec_y - 14, f"Threads (approx): {int(round(total_threads))}")
    c.drawString(
        56,
        spec_y - 28,
        f"Pitch: {avg_pitch:.3f} mm" if avg_pitch is not None else "Pitch: N/A (unthreaded)",
    )
    if pitch_values and len(set(round(v, 6) for v in pitch_values)) > 1:
        c.drawString(56, spec_y - 42, "Note: Multiple pitch values detected across thread regions.")

    # Bottom-right title block
    tb_w = 300
    tb_h = 88
    tb_x = page_w - tb_w - 24
    tb_y = 24
    c.rect(tb_x, tb_y, tb_w, tb_h, stroke=1, fill=0)
    c.line(tb_x, tb_y + tb_h - 24, tb_x + tb_w, tb_y + tb_h - 24)
    c.line(tb_x + 190, tb_y, tb_x + 190, tb_y + tb_h - 24)
    c.line(tb_x + 120, tb_y, tb_x + 120, tb_y + tb_h - 24)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(tb_x + 6, tb_y + tb_h - 17, "TITLE BLOCK")
    c.setFont("Helvetica", 8)
    c.drawString(tb_x + 6, tb_y + 56, "PART NAME")
    c.drawString(tb_x + 6, tb_y + 42, screw_label[:33])
    c.drawString(tb_x + 6, tb_y + 27, "DRAWN BY")
    c.drawString(tb_x + 6, tb_y + 13, author[:22])
    c.drawString(tb_x + 126, tb_y + 56, "DATE")
    c.drawString(tb_x + 126, tb_y + 42, datetime.now().strftime("%Y-%m-%d"))
    c.drawString(tb_x + 196, tb_y + 56, "HEAD/DRIVE")
    c.drawString(tb_x + 196, tb_y + 42, f"{spec.head.type.title()} / {drive.title()}")
    c.drawString(tb_x + 196, tb_y + 27, "SCALE")
    c.drawString(tb_x + 196, tb_y + 13, "NTS")
    c.save()


def _attempt_build(chat: ChatState) -> dict[str, Any]:
    def _prompt(q: str) -> str:
        if q in chat.answers:
            return chat.answers[q]
        raise _NeedInput(q)

    try:
        spec = screw_spec_from_query(chat.query, prompt=_prompt)
    except _NeedInput as need:
        chat.pending_question = need.question
        return {
            "status": "needs_input",
            "question": need.question,
            "message": _bot(chat, need.question, kind="question"),
        }
    except Exception as exc:
        chat.pending_question = None
        return {
            "status": "error",
            "error": str(exc),
            "message": _bot(chat, f"Could not generate screw: {exc}", kind="error"),
        }

    try:
        from .assembly import make_screw_from_spec
        from .export import export_step, export_stl
        from cadquery import exporters
    except ModuleNotFoundError as exc:
        chat.pending_question = None
        return {
            "status": "error",
            "error": str(exc),
            "message": _bot(
                chat,
                "CAD runtime is missing (CadQuery/OCP). Install a compatible runtime to generate geometry.",
                kind="error",
            ),
        }

    chat.pending_question = None
    stamp = int(time.time() * 1000)
    head_tag = f"{spec.head.type}_hd{spec.head.d:.2f}_L{spec.shaft.L:.2f}"
    if spec.drive is not None:
        head_tag += f"_{spec.drive.type}"
    if any(isinstance(r, ThreadRegionSpec) for r in spec.regions):
        head_tag += "_threaded"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", head_tag).strip("_").lower()
    stem = f"{slug}_{stamp}"
    screw = make_screw_from_spec(spec, include_thread_markers=False)
    step_path = export_step(screw, _DOWNLOAD_DIR / f"{stem}.step")
    stl_path = export_stl(screw, _DOWNLOAD_DIR / f"{stem}.stl")
    preview_path = _DOWNLOAD_DIR / f"{stem}.svg"
    drawing_path = _DOWNLOAD_DIR / f"{stem}_drawing.pdf"
    bundle_path = _DOWNLOAD_DIR / f"{stem}_bundle.zip"
    try:
        exporters.export(screw, str(preview_path), exportType="SVG")
        preview_url = f"/downloads/{preview_path.name}"
    except Exception:
        preview_url = ""
    try:
        _write_engineering_drawing_pdf(spec, drawing_path, screw_name=chat.title, author_name=Path.home().name)
        drawing_url = f"/downloads/{drawing_path.name}"
    except Exception:
        drawing_url = ""
    try:
        with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(step_path, arcname=step_path.name)
            bundle.write(stl_path, arcname=stl_path.name)
            if drawing_url:
                bundle.write(drawing_path, arcname=drawing_path.name)
        bundle_url = f"/downloads/{bundle_path.name}"
    except Exception:
        bundle_url = ""

    step_url = f"/downloads/{step_path.name}"
    stl_url = f"/downloads/{stl_path.name}"
    chat.latest_files = {
        "step_url": step_url,
        "stl_url": stl_url,
        "preview_url": preview_url,
        "drawing_url": drawing_url,
        "bundle_url": bundle_url,
    }
    msg = _bot(
        chat,
        "Screw generated. Use the buttons to download STEP, STL, drawing PDF, or a ZIP bundle.",
        kind="result",
        extra=chat.latest_files,
    )
    return {"status": "ok", "message": msg}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = _WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/chats", response_model=list[ChatSummary])
def list_chats() -> list[ChatSummary]:
    return [
        ChatSummary(id=c.id, title=c.title)
        for c in sorted(_chats.values(), key=lambda x: x.id)
    ]


@app.delete("/api/chats")
def clear_chats() -> dict[str, Any]:
    _chats.clear()
    return {"ok": True}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: int) -> dict[str, Any]:
    if chat_id not in _chats:
        raise HTTPException(status_code=404, detail="Chat not found.")
    del _chats[chat_id]
    return {"ok": True}


@app.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: int, body: RenameChatIn) -> dict[str, Any]:
    chat = _chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty.")
    chat.title = title
    return {"ok": True, "id": chat.id, "title": chat.title}


@app.post("/api/chats")
def create_chat() -> dict[str, Any]:
    chat = _new_chat()
    _bot(chat, "Describe your screw in plain text. I will ask follow-up questions when needed.")
    return {"id": chat.id, "title": chat.title, "messages": chat.messages}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int) -> dict[str, Any]:
    chat = _chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return {
        "id": chat.id,
        "title": chat.title,
        "messages": chat.messages,
        "pending_question": chat.pending_question,
        "latest_files": chat.latest_files,
    }


@app.patch("/api/chats/{chat_id}/messages/{msg_idx}")
def edit_message(chat_id: int, msg_idx: int, body: EditMessageIn) -> dict[str, Any]:
    chat = _chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    if msg_idx < 0 or msg_idx >= len(chat.messages):
        raise HTTPException(status_code=404, detail="Message not found.")
    message = chat.messages[msg_idx]
    if message.get("role") != "user":
        raise HTTPException(status_code=400, detail="Only user messages can be edited.")
    latest_user_idx = max((i for i, m in enumerate(chat.messages) if m.get("role") == "user"), default=-1)
    if msg_idx != latest_user_idx:
        raise HTTPException(status_code=400, detail="Only the latest user message can be edited.")

    updated = body.content.strip()
    if not updated:
        raise HTTPException(status_code=400, detail="Edited message cannot be empty.")
    message["content"] = updated

    # Recompute the latest bot response from this edited user message.
    chat.messages = chat.messages[: msg_idx + 1]
    chat.query = updated
    chat.answers = {}
    chat.pending_question = None
    parsed = parse_query(updated)
    if parsed.head_type is not None:
        threadish = ("thread" in updated.lower()) or ("tpi" in updated.lower()) or (parsed.pitch is not None)
        chat.title = f"{parsed.head_type.title()} {'Threaded ' if threadish else ''}Screw"
    result = _attempt_build(chat)
    return {
        "ok": True,
        "result": result,
        "messages": chat.messages,
        "pending_question": chat.pending_question,
    }


@app.post("/api/chats/{chat_id}/messages")
def post_message(chat_id: int, body: MessageIn) -> dict[str, Any]:
    chat = _chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    raw = body.content
    content = raw.strip()
    if chat.pending_question is None and not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    # Allow empty reply when prompt says "Press Enter to continue."
    if content:
        _user(chat, content)

    if chat.pending_question is None:
        chat.query = content
        chat.answers = {}
        parsed = parse_query(content)
        if parsed.head_type is not None:
            threadish = ("thread" in content.lower()) or ("tpi" in content.lower()) or (parsed.pitch is not None)
            chat.title = f"{parsed.head_type.title()} {'Threaded ' if threadish else ''}Screw"
    else:
        chat.answers[chat.pending_question] = content

    result = _attempt_build(chat)
    return {"chat_id": chat.id, **result, "messages": chat.messages, "pending_question": chat.pending_question}

