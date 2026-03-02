"""Local chat-style web app for interactive fastener generation."""

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

from .search_parser import screw_spec_from_query
from .spec import ScrewSpec, ShaftSpec, ThreadRegionSpec


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
    pending_flow: str | None = None
    latest_spec: ScrewSpec | None = None


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

app = FastAPI(title="Fastener Generator Chat")
app.mount("/assets", StaticFiles(directory=_WEB_DIR), name="assets")
app.mount("/downloads", StaticFiles(directory=_DOWNLOAD_DIR), name="downloads")

_chat_counter = itertools.count(1)
_chats: dict[int, ChatState] = {}
_Q_MATCH_NUT = "Do you want a matching nut?"
_Q_MATCH_NUT_STYLE = "What style for the matching nut?"


def _new_chat(title: str | None = None) -> ChatState:
    cid = next(_chat_counter)
    chat = ChatState(id=cid, title=title or "New Fastener")
    _chats[cid] = chat
    return chat


def _normalize_chat_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return "New Fastener"
    if t.lower() == "new fastener":
        return "New Fastener"
    if t.endswith(" Fastener"):
        return t[: -len(" Fastener")] + " Fastener"
    return t


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


def _chat_title_for_spec(spec) -> str:
    threadish = any(isinstance(r, ThreadRegionSpec) for r in spec.regions)
    kind = "Bolt" if spec.fastener_type == "bolt" else "Fastener"
    return f"{spec.head.type.title()} {'Threaded ' if threadish else ''}{kind}"


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

  <text x="40" y="42" class="title">Fastener Engineering Drawing</text>
  <text x="40" y="70" class="small">Type: {esc(spec.head.type)} | Drive: {esc(drive)} | Generated by Fastener Generator</text>

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
    iso_svg_path: Path | None = None,
) -> None:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    author = (author_name or Path.home().name or "User").strip() or "User"
    screw_label = (screw_name or f"{spec.head.type.title()} {spec.fastener_type.title()}").strip()

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

    page_w, page_h = landscape(A4)
    c = canvas.Canvas(str(output_path), pagesize=landscape(A4))
    c.setTitle(f"{screw_label} Drawing")

    def _dim_h(
        x1: float,
        x2: float,
        y: float,
        ext_y: float,
        label: str,
        label_dy: float = 4.5,
        label_dx: float = 0.0,
        label_align: str = "center",
        label_x: float | None = None,
    ) -> None:
        c.line(x1, ext_y, x1, y)
        c.line(x2, ext_y, x2, y)
        c.line(x1, y, x2, y)
        ah = 4
        c.line(x1, y, x1 + ah, y + 1.4)
        c.line(x1, y, x1 + ah, y - 1.4)
        c.line(x2, y, x2 - ah, y + 1.4)
        c.line(x2, y, x2 - ah, y - 1.4)
        c.setFont("Helvetica", 8)
        if label_align == "left":
            x_txt = label_x if label_x is not None else (x1 + label_dx)
            c.drawString(x_txt, y + label_dy, label)
        else:
            c.drawCentredString((x1 + x2) * 0.5 + label_dx, y + label_dy, label)

    def _dim_v(
        x: float,
        y1: float,
        y2: float,
        ext_x: float,
        label: str,
        label_dx: float = 4,
        label_dy: float = -2,
        label_mode: str = "center",
        label_x: float | None = None,
    ) -> None:
        c.line(ext_x, y1, x, y1)
        c.line(ext_x, y2, x, y2)
        c.line(x, y1, x, y2)
        ah = 4
        c.line(x, y1, x + 1.4, y1 + ah)
        c.line(x, y1, x - 1.4, y1 + ah)
        c.line(x, y2, x + 1.4, y2 - ah)
        c.line(x, y2, x - 1.4, y2 - ah)
        c.setFont("Helvetica", 8)
        if label_mode == "above":
            lx = label_x if label_x is not None else (x + label_dx)
            c.drawString(lx, y1 + 8 + label_dy, label)
        elif label_mode == "below":
            lx = label_x if label_x is not None else (x + label_dx)
            c.drawString(lx, y2 - 12 + label_dy, label)
        else:
            c.drawString(x + label_dx, (y1 + y2) * 0.5 + label_dy, label)

    # Drafting frame with zone labels.
    frame_margin = 14
    zone_band = 14
    fx = frame_margin
    fy = frame_margin
    fw = page_w - 2 * frame_margin
    fh = page_h - 2 * frame_margin
    ix = fx + zone_band
    iy = fy + zone_band
    iw = fw - 2 * zone_band
    ih = fh - 2 * zone_band

    c.rect(fx, fy, fw, fh, stroke=1, fill=0)
    c.rect(ix, iy, iw, ih, stroke=1, fill=0)

    col_labels = ["1", "2", "3", "4", "5", "6"]
    row_labels = ["A", "B", "C", "D", "E"]
    col_w = iw / len(col_labels)
    row_h = ih / len(row_labels)
    c.setFont("Helvetica", 8)
    for i, lab in enumerate(col_labels):
        x = ix + i * col_w
        c.rect(x, iy + ih, col_w, zone_band, stroke=1, fill=0)
        c.rect(x, fy, col_w, zone_band, stroke=1, fill=0)
        c.drawCentredString(x + col_w * 0.5, iy + ih + 4, lab)
        c.drawCentredString(x + col_w * 0.5, fy + 4, lab)
    for i, lab in enumerate(row_labels):
        y = iy + i * row_h
        c.rect(fx, y, zone_band, row_h, stroke=1, fill=0)
        c.rect(ix + iw, y, zone_band, row_h, stroke=1, fill=0)
        c.drawCentredString(fx + zone_band * 0.5, y + row_h * 0.5 - 2, lab)
        c.drawCentredString(ix + iw + zone_band * 0.5, y + row_h * 0.5 - 2, lab)

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(ix + 44, iy + ih - 22, "Engineering Drawing")
    c.setFont("Helvetica", 9)
    c.drawString(ix + 44, iy + ih - 36, f"Fastener: {screw_label}")
    c.drawString(ix + 44, iy + ih - 49, f"Head: {spec.head.type.title()} | Drive: {drive.title()} | Units: mm")

    # Side view: landscape layout with dynamic scale to avoid view overlap.
    side_x = ix + 44
    side_y = iy + ih * 0.68
    top_cx = ix + iw * 0.82
    top_cy = side_y
    base_px = min((iw * 0.60) / max(length + head_h, 1e-6), 13.5)
    top_r = min(max(0.5 * head_d * base_px * 0.66, 15.0), 34.0)
    side_len_max = max(120.0, (top_cx - top_r - 95.0) - side_x)
    px_per_mm = min(side_len_max / max(length + head_h, 1e-6), 13.5)

    # Keep side-view geometry in true proportion so head height/diameter ratio is accurate.
    shank_r = 0.5 * shaft_d * px_per_mm
    head_r = 0.5 * head_d * px_per_mm
    root_r = 0.5 * root_d * px_per_mm
    head_px = head_h * px_per_mm
    tip_px = tip_len * px_per_mm
    body_px = (length - tip_len) * px_per_mm
    x_body0 = side_x + head_px
    x_tip0 = x_body0 + body_px
    x_tip_end = x_tip0 + tip_px

    # Side-view profile.
    if spec.head.type == "flat":
        # Flat head is countersunk: draw a trapezoid/conical profile.
        c.line(side_x, side_y - head_r, x_body0, side_y - root_r)
        c.line(x_body0, side_y - root_r, x_body0, side_y + root_r)
        c.line(x_body0, side_y + root_r, side_x, side_y + head_r)
        c.line(side_x, side_y + head_r, side_x, side_y - head_r)
    else:
        c.rect(side_x, side_y - head_r, head_px, 2 * head_r, stroke=1, fill=0)
    if spec.head.type == "hex":
        # Hex side view style requested: rectangular head with three horizontal lines.
        for frac in (-0.45, 0.0, 0.45):
            y = side_y + frac * head_r
            c.line(side_x + 2, y, x_body0 - 2, y)

    c.rect(x_body0, side_y - root_r, body_px, 2 * root_r, stroke=1, fill=0)
    if spec.fastener_type == "bolt":
        # Bolt end: strictly flat (no tip / no chamfer).
        if tip_px > 1e-9:
            c.rect(x_tip0, side_y - root_r, tip_px, 2 * root_r, stroke=1, fill=0)
    else:
        c.line(x_tip0, side_y - root_r, x_tip_end, side_y)
        c.line(x_tip_end, side_y, x_tip0, side_y + root_r)
        c.line(x_tip0, side_y + root_r, x_tip0, side_y - root_r)
    c.setDash([2, 2], 0)
    c.line(x_body0, side_y - shank_r, x_tip0, side_y - shank_r)
    c.line(x_body0, side_y + shank_r, x_tip0, side_y + shank_r)
    c.setDash([], 0)

    # Thread rendering by region span (cleaner and lighter).
    for kind, start_mm, end_mm, p in region_ranges:
        if kind != "thread":
            continue
        start_x = x_body0 + start_mm * px_per_mm
        end_x = x_body0 + min(end_mm, length - tip_len) * px_per_mm
        pitch_here = p if p is not None and p > 0 else max(0.8, 0.25 * shaft_d)
        crest_count = max(2, int((end_mm - start_mm) / pitch_here))
        for i in range(crest_count):
            x = start_x + (i + 0.5) * (end_x - start_x) / crest_count
            c.setLineWidth(0.6)
            c.line(x - 1.8, side_y - shank_r, x + 1.8, side_y - root_r)
            c.line(x - 1.8, side_y + shank_r, x + 1.8, side_y + root_r)
        c.setLineWidth(1)

    # Top view: right side and centerline aligned with side view.
    top_r = min(max(0.5 * head_d * px_per_mm * 0.58, 14.0), 28.0)
    if spec.head.type == "hex":
        pts = []
        for k in range(6):
            a = 0.523599 + k * 1.047198
            pts.append((top_cx + top_r * math.cos(a), top_cy + top_r * math.sin(a)))
        for i in range(6):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 6]
            c.line(x1, y1, x2, y2)
    else:
        c.circle(top_cx, top_cy, top_r, stroke=1, fill=0)
    # Centerlines: dashed so drive outline remains the dominant visible feature.
    c.setDash([2, 2], 0)
    c.setLineWidth(0.8)
    c.line(top_cx - top_r * 1.1, top_cy, top_cx + top_r * 1.1, top_cy)
    c.line(top_cx, top_cy - top_r * 1.1, top_cx, top_cy + top_r * 1.1)
    c.setDash([], 0)
    c.setLineWidth(1.2)
    if drive == "phillips":
        c.line(top_cx - top_r * 0.48, top_cy, top_cx + top_r * 0.48, top_cy)
        c.line(top_cx, top_cy - top_r * 0.48, top_cx, top_cy + top_r * 0.48)
    elif drive == "torx":
        c.circle(top_cx, top_cy, top_r * 0.28, stroke=1, fill=0)
        c.circle(top_cx, top_cy, top_r * 0.17, stroke=1, fill=0)
    elif drive == "hex":
        r = top_r * 0.30
        pts = []
        for k in range(6):
            a = 0.523599 + k * 1.047198
            pts.append((top_cx + r * math.cos(a), top_cy + r * math.sin(a)))
        for i in range(6):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 6]
            c.line(x1, y1, x2, y2)
    c.setLineWidth(1)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(side_x, side_y + head_r + 22, "SIDE VIEW")
    c.drawString(top_cx - 24, top_cy + top_r + 18, "TOP VIEW")

    overall_len = head_h + length
    # Head-height dimension intentionally closer to the part than full-length.
    _dim_h(
        side_x,
        x_body0,
        side_y - head_r - 14,
        side_y - head_r,
        f"Head Height = {head_h:.2f}",
        label_dy=6.0,
        label_align="left",
        label_x=x_body0 + 6.0,
    )
    _dim_h(
        x_body0,
        x_tip_end,
        side_y - head_r - 31,
        side_y - head_r,
        f"Shaft Length = {length:.2f}",
        label_dy=5.5,
        label_dx=0.0,
    )
    _dim_h(side_x, x_tip_end, side_y - head_r - 48, side_y - head_r, f"Full Length = {overall_len:.2f}", label_dy=5.5)
    if spec.fastener_type != "bolt":
        _dim_h(
            x_tip0,
            x_tip_end,
            side_y - root_r - 22,
            side_y - root_r,
            f"Tip Length = {tip_len:.2f}",
            label_dy=4.0,
            label_align="left",
            label_x=x_tip_end + 8.0,
        )
    _dim_h(
        x_body0,
        x_body0 + threaded_len * px_per_mm,
        side_y + shank_r + 18,
        side_y + shank_r,
        f"Threaded = {threaded_len:.2f}",
    )
    _dim_v(
        x_tip_end + 30,
        side_y - shank_r ,
        side_y + shank_r,
        x_tip_end,
        "",
    )
    c.setFont("Helvetica", 8)
    c.drawString(x_tip_end + 16.0, side_y + shank_r + 10.0, f"Max Dia = {shaft_d:.2f}")
    _dim_v(
        x_tip_end + 84,
        side_y - root_r,
        side_y + root_r,
        x_tip_end,
        f"Root Dia = {root_d:.2f}",
        label_mode="below",
        label_x=x_tip_end + 88.0,
        label_dy=0.0,
    )
    _dim_v(
        top_cx + top_r + 30,
        top_cy - top_r,
        top_cy + top_r,
        top_cx + top_r,
        f"Head Dia = {head_d:.2f}",
        label_dx=10,
        label_dy=-2,
    )

    c.setFont("Helvetica", 8.5)
    spec_y = iy + 78
    c.drawString(ix + 24, spec_y + 30, f"Shank/Shaft Diameter: {shaft_d:.2f} mm")
    c.drawString(ix + 24, spec_y + 16, f"Threads (approx): {int(round(total_threads))}")
    c.drawString(ix + 24, spec_y + 2, f"Pitch: {avg_pitch:.3f} mm" if avg_pitch is not None else "Pitch: N/A")
    if pitch_values and len(set(round(v, 6) for v in pitch_values)) > 1:
        c.drawString(ix + 10, spec_y - 12, "Note: Multiple pitch values detected across thread regions.")

    # Precompute title block box so isometric can be placed to its left.
    tb_w = 285
    tb_h = 108
    tb_x = ix + iw - tb_w - 8
    tb_y = iy + 6

    # Isometric view: prefer actual model snapshot exported as SVG.
    iso_x = ix + iw * 0.40
    iso_target_w = max(210.0, tb_x - iso_x - 14.0)
    # Make isometric visibly larger while keeping the same placement.
    iso_target_h = max(150.0, 1.9 * row_h)
    iso_y = iy + 18.0
    c.setFont("Helvetica-Bold", 9)
    c.drawString(iso_x - 86.0, iso_y + iso_target_h * 0.78, "ISOMETRIC VIEW")
    drew_iso = False
    if iso_svg_path is not None and iso_svg_path.exists():
        try:
            from reportlab.graphics import renderPDF
            from svglib.svglib import svg2rlg

            drawing = svg2rlg(str(iso_svg_path))
            if drawing is not None:
                x1, y1, x2, y2 = drawing.getBounds()
                w = max(1e-6, x2 - x1)
                h = max(1e-6, y2 - y1)
                scale = min(iso_target_w / w, iso_target_h / h)
                c.saveState()
                c.translate(iso_x, iso_y)
                c.scale(scale, scale)
                c.translate(-x1, -y1)
                renderPDF.draw(drawing, c, 0, 0)
                c.restoreState()
                drew_iso = True
        except Exception:
            drew_iso = False
    if not drew_iso:
        # Fallback: simple colored profile if SVG import is unavailable.
        c.setStrokeColorRGB(0.15, 0.2, 0.35)
        c.setFillColorRGB(0.74, 0.8, 0.92)
        bx = iso_x + 10
        by = iso_y + 16
        c.rect(bx, by, 66, 12, stroke=1, fill=1)
        c.rect(bx + 66, by + 1.5, 26, 9, stroke=1, fill=1)
        c.setFillColorRGB(0.15, 0.2, 0.35)
        c.line(bx + 8, by + 1.5, bx + 56, by + 1.5)
        c.line(bx + 8, by + 10.5, bx + 56, by + 10.5)
        c.setFillColorRGB(0, 0, 0)

    # MYSA title block in bottom-right corner.
    c.rect(tb_x, tb_y, tb_w, tb_h, stroke=1, fill=0)
    # Header strip + dedicated part-name row + info grid.
    y_hdr = tb_y + tb_h - 20
    y_part = y_hdr - 22
    c.line(tb_x, y_hdr, tb_x + tb_w, y_hdr)
    c.line(tb_x, y_part, tb_x + tb_w, y_part)
    grid_h = y_part - tb_y
    mid_y = tb_y + grid_h / 2
    col1 = tb_x + tb_w / 3
    col2 = tb_x + 2 * tb_w / 3
    c.line(col1, tb_y, col1, y_part)
    c.line(col2, tb_y, col2, y_part)
    c.line(tb_x, mid_y, tb_x + tb_w, mid_y)

    c.setFont("Helvetica-Bold", 10)
    c.drawString(tb_x + 8, tb_y + tb_h - 14, "MYSA")
    c.setFont("Helvetica", 8.2)
    c.drawString(tb_x + 8, y_part + 8, "PART NAME")
    c.setFont("Helvetica", 7.8)
    c.drawString(tb_x + 66, y_part + 8, screw_label[:42])

    pad = 8
    row_h = (y_part - tb_y) / 2
    top_row_top = y_part
    bot_row_top = tb_y + row_h
    label_drop = 12
    value_drop = 25

    def _cell(col_left: float, row_top: float, label: str, value: str) -> None:
        c.setFont("Helvetica", 7.6)
        c.drawString(col_left + pad, row_top - label_drop, label)
        c.setFont("Helvetica", 8.0)
        c.drawString(col_left + pad, row_top - value_drop, value)

    # Row 1 (three cells): drawn by / approved by / date
    _cell(tb_x, top_row_top, "DRAWN BY", author[:20])
    _cell(col1, top_row_top, "APPROVED BY", "Mysa")
    _cell(col2, top_row_top, "DATE", datetime.now().strftime("%Y-%m-%d"))
    # Row 2 (three cells): units / head-drive / scale
    _cell(tb_x, bot_row_top, "UNITS", "mm")
    _cell(col1, bot_row_top, "HEAD / DRIVE", f"{spec.head.type.title()}/{drive.title()}"[:14])
    _cell(col2, bot_row_top, "SCALE", "NTS")
    c.save()


def _write_nut_drawing_pdf(
    *,
    style_name: str,
    across: float,
    major_d: float,
    pitch: float,
    nut_h: float,
    output_path: Path,
) -> None:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    page_w, page_h = landscape(A4)
    c = canvas.Canvas(str(output_path), pagesize=(page_w, page_h))
    c.setTitle(f"Matching {style_name} Nut Drawing")

    margin = 18
    ix, iy = margin, margin
    iw, ih = page_w - 2 * margin, page_h - 2 * margin
    c.rect(ix, iy, iw, ih, stroke=1, fill=0)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(ix + 16, iy + ih - 24, "Nut Engineering Drawing")
    c.setFont("Helvetica", 9)
    c.drawString(ix + 16, iy + ih - 38, f"Part: Matching {style_name} Nut")

    # Top view
    top_cx, top_cy = ix + 170, iy + ih * 0.58
    top_r = 52
    c.setFont("Helvetica-Bold", 9)
    c.drawString(top_cx - 24, top_cy + top_r + 20, "TOP VIEW")
    c.setLineWidth(1.2)
    if style_name.lower().startswith("hex"):
        pts = []
        for k in range(6):
            a = 0.523599 + k * 1.047198
            pts.append((top_cx + top_r * math.cos(a), top_cy + top_r * math.sin(a)))
        for i in range(6):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 6]
            c.line(x1, y1, x2, y2)
    else:
        s = top_r * 1.5
        c.rect(top_cx - s / 2, top_cy - s / 2, s, s, stroke=1, fill=0)
    c.circle(top_cx, top_cy, max(6.0, major_d * 4.0), stroke=1, fill=0)

    # Side view
    sx, sy = ix + 320, iy + ih * 0.48
    side_w = 170
    side_h = 90
    c.setFont("Helvetica-Bold", 9)
    c.drawString(sx + 42, sy + side_h / 2 + 36, "SIDE VIEW")
    c.setLineWidth(1.2)
    c.rect(sx, sy - side_h / 2, side_w, side_h, stroke=1, fill=0)
    c.setDash([2, 2], 0)
    bore_half = max(8.0, major_d * 3.2)
    c.line(sx + side_w * 0.25, sy - bore_half, sx + side_w * 0.25, sy + bore_half)
    c.line(sx + side_w * 0.75, sy - bore_half, sx + side_w * 0.75, sy + bore_half)
    c.setDash([], 0)

    # Dimension notes
    c.setFont("Helvetica", 9)
    c.drawString(ix + 16, iy + 82, f"Across Flats / Width: {across:.2f} mm")
    c.drawString(ix + 16, iy + 66, f"Thickness: {nut_h:.2f} mm")
    c.drawString(ix + 16, iy + 50, f"Thread Major Dia: {major_d:.2f} mm")
    c.drawString(ix + 16, iy + 34, f"Pitch: {pitch:.3f} mm")

    c.save()


def _is_yes(answer: str) -> bool:
    return answer.strip().lower() in {"y", "yes"}


def _build_matching_nut(chat: ChatState, base: ScrewSpec, nut_style: str) -> dict[str, Any]:
    try:
        import cadquery as cq
        from cadquery import exporters

        from .threads import ThreadParams, apply_external_thread
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

    first_tr = next((r for r in base.regions if isinstance(r, ThreadRegionSpec)), None)
    if first_tr is None:
        return {
            "status": "error",
            "error": "No threaded region available for matching nut.",
            "message": _bot(chat, "No thread region found, so I can't generate a matching nut.", kind="error"),
        }

    major_d = float(first_tr.major_d if first_tr.major_d is not None else base.shaft.d_minor * 1.15)
    pitch = float(first_tr.pitch)
    thread_height = first_tr.thread_height
    nut_h = max(0.7 * major_d, min(1.0 * major_d, 0.85 * major_d))
    style = nut_style.strip().lower()

    if style.startswith("hex"):
        af = max(1.6 * major_d, base.head.d)
        # polygon(d) uses vertex-to-vertex diameter for regular polygons.
        poly_d = 2.0 * af / (3.0**0.5)
        body = cq.Workplane("XY").polygon(6, poly_d).extrude(nut_h)
        style_name = "Hex"
    else:
        w = max(1.45 * major_d, 0.9 * base.head.d)
        body = cq.Workplane("XY").rect(w, w).extrude(nut_h)
        style_name = "Square"

    body = body.translate((0, 0, -nut_h / 2.0))

    # Build a threaded male "tap" and subtract it to get a matching internal thread.
    tap_len = nut_h + 2.0
    tap_spec = ShaftSpec(d_minor=base.shaft.d_minor, L=tap_len, tip_len=0.0)
    tap_core = cq.Workplane("XY").circle(base.shaft.d_minor / 2.0).extrude(tap_len).translate((0, 0, -nut_h / 2.0 - 1.0))
    try:
        tap = apply_external_thread(
            tap_core,
            tap_spec,
            ThreadParams(
                pitch=pitch,
                length=nut_h,
                start_from_head=1.0,
                included_angle_deg=60.0,
                major_d=major_d,
                thread_height=thread_height,
                mode="add",
            ),
        )
        nut = body.cut(tap)
    except Exception:
        # Fallback to a simple clearance bore if helical subtraction is unstable.
        bore_r = major_d / 2.0 + 0.08
        bore = cq.Workplane("XY").circle(bore_r).extrude(nut_h + 2.0).translate((0, 0, -nut_h / 2.0 - 1.0))
        nut = body.cut(bore)

    stamp = int(time.time() * 1000)
    stem = f"matching_nut_{style_name.lower()}_d{major_d:.2f}_p{pitch:.2f}_{stamp}"
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_").lower()
    step_path = _DOWNLOAD_DIR / f"{stem}.step"
    stl_path = _DOWNLOAD_DIR / f"{stem}.stl"
    preview_path = _DOWNLOAD_DIR / f"{stem}.svg"
    drawing_path = _DOWNLOAD_DIR / f"{stem}_drawing.pdf"
    bundle_path = _DOWNLOAD_DIR / f"{stem}_bundle.zip"

    from .export import export_step, export_stl

    export_step(nut, step_path)
    export_stl(nut, stl_path)
    try:
        exporters.export(
            nut,
            str(preview_path),
            exportType="SVG",
            opt={"projectionDir": (0.7, -0.5, 0.7), "showAxes": False, "showHidden": False},
        )
        preview_url = f"/downloads/{preview_path.name}"
    except Exception:
        preview_url = ""

    drawing_url = ""
    try:
        across = af if style.startswith("hex") else w
        _write_nut_drawing_pdf(
            style_name=style_name,
            across=float(across),
            major_d=major_d,
            pitch=pitch,
            nut_h=nut_h,
            output_path=drawing_path,
        )
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

    chat.latest_files = {
        "step_url": f"/downloads/{step_path.name}",
        "stl_url": f"/downloads/{stl_path.name}",
        "preview_url": preview_url,
        "drawing_url": drawing_url,
        "bundle_url": bundle_url,
    }
    msg = _bot(
        chat,
        f"Matching {style_name.lower()} nut generated. Use the buttons to download STEP, STL, drawing PDF, or a ZIP bundle.",
        kind="result",
        extra=chat.latest_files,
    )
    return {"status": "ok", "message": msg}


def _build_from_spec(chat: ChatState, spec: ScrewSpec) -> dict[str, Any]:
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
    chat.title = _chat_title_for_spec(spec)
    stamp = int(time.time() * 1000)
    head_tag = f"{spec.fastener_type}_{spec.head.type}_hd{spec.head.d:.2f}_L{spec.shaft.L:.2f}"
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
        if spec.head.type == "flat":
            # For flat heads, flip preview orientation so the drive/head face
            # is presented toward the viewer instead of the underside.
            preview_model = screw.rotate((0, 0, 0), (1, 0, 0), 180)
            exporters.export(
                preview_model,
                str(preview_path),
                exportType="SVG",
                opt={"projectionDir": (0.25, -0.15, 1.0), "showAxes": False, "showHidden": False},
            )
        else:
            exporters.export(screw, str(preview_path), exportType="SVG")
        preview_url = f"/downloads/{preview_path.name}"
    except Exception:
        preview_url = ""
    try:
        iso_preview_path = _DOWNLOAD_DIR / f"{stem}_iso.svg"
        try:
            iso_model = screw
            if spec.head.type != "flat":
                # Drawing-only orientation tweak: keep flat heads as-is,
                # rotate other heads so they appear upright in isometric view.
                iso_model = screw.rotate((0, 0, 0), (1, 0, 0), 180)
            exporters.export(
                iso_model,
                str(iso_preview_path),
                exportType="SVG",
                opt={"projectionDir": (-1.0, 1.0, 0.75), "showAxes": False, "showHidden": False},
            )
        except Exception:
            iso_preview_path = None

        _write_engineering_drawing_pdf(
            spec,
            drawing_path,
            screw_name=chat.title,
            author_name=Path.home().name,
            iso_svg_path=iso_preview_path,
        )
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
    fastener_word = "Bolt" if spec.fastener_type == "bolt" else "Fastener"
    msg = _bot(
        chat,
        f"{fastener_word} generated. Use the buttons to download STEP, STL, drawing PDF, or a ZIP bundle.",
        kind="result",
        extra=chat.latest_files,
    )
    return {"status": "ok", "message": msg}


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
            "message": _bot(chat, f"Could not generate fastener: {exc}", kind="error"),
        }
    chat.latest_spec = spec
    return _build_from_spec(chat, spec)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = _WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/chats", response_model=list[ChatSummary])
def list_chats() -> list[ChatSummary]:
    for chat in _chats.values():
        chat.title = _normalize_chat_title(chat.title)
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
    _bot(chat, "Describe your fastener in plain text. I will ask follow-up questions when needed.")
    return {"id": chat.id, "title": chat.title, "messages": chat.messages}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int) -> dict[str, Any]:
    chat = _chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    chat.title = _normalize_chat_title(chat.title)
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
    chat.pending_flow = None
    chat.latest_spec = None
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

    if chat.pending_flow == "matching_nut_offer":
        if content:
            _user(chat, content)
        if _is_yes(content):
            chat.pending_flow = "matching_nut_style"
            chat.pending_question = _Q_MATCH_NUT_STYLE
            _bot(chat, _Q_MATCH_NUT_STYLE, kind="question")
            return {
                "chat_id": chat.id,
                "status": "needs_input",
                "question": chat.pending_question,
                "messages": chat.messages,
                "pending_question": chat.pending_question,
            }
        chat.pending_flow = None
        chat.pending_question = None
        _bot(chat, "Okay, skipped matching nut.", kind="text")
        return {
            "chat_id": chat.id,
            "status": "ok",
            "messages": chat.messages,
            "pending_question": chat.pending_question,
        }

    if chat.pending_flow == "matching_nut_style":
        if content:
            _user(chat, content)
        base = chat.latest_spec
        if base is None:
            chat.pending_flow = None
            chat.pending_question = None
            _bot(chat, "Couldn't find the previous fastener to match. Please generate again.", kind="error")
            return {
                "chat_id": chat.id,
                "status": "error",
                "messages": chat.messages,
                "pending_question": chat.pending_question,
            }
        choice = content.lower()
        nut_style = "hex" if "hex" in choice else "square"
        chat.pending_flow = None
        chat.pending_question = None
        result = _build_matching_nut(chat, base, nut_style)
        return {"chat_id": chat.id, **result, "messages": chat.messages, "pending_question": chat.pending_question}

    if chat.pending_question is None and not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    # Allow empty reply when prompt says "Press Enter to continue."
    if content:
        _user(chat, content)

    if chat.pending_question is None:
        chat.query = content
        chat.answers = {}
    else:
        chat.answers[chat.pending_question] = content

    result = _attempt_build(chat)
    if (
        result.get("status") == "ok"
        and chat.latest_spec is not None
        and chat.pending_flow is None
        and chat.pending_question is None
    ):
        chat.pending_flow = "matching_nut_offer"
        chat.pending_question = _Q_MATCH_NUT
        _bot(chat, _Q_MATCH_NUT, kind="question")
    return {"chat_id": chat.id, **result, "messages": chat.messages, "pending_question": chat.pending_question}

