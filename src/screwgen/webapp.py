"""Local chat-style web app for interactive fastener generation."""

from __future__ import annotations

import itertools
import json
import math
import os
import re
import zipfile
import base64
import urllib.request
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
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
    image_estimate_query: str | None = None


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
_BRAND_BG = _WEB_DIR / "brand-bg.png"

app = FastAPI(title="Fastener Generator Chat")
app.mount("/assets", StaticFiles(directory=_WEB_DIR), name="assets")

_chat_counter = itertools.count(1)
_chats: dict[int, ChatState] = {}
_Q_MATCH_NUT = "Do you want a matching nut?"
_Q_MATCH_NUT_STYLE = "What style for the matching nut?"
_Q_NUT_SHAPE = "What shape for the nut?"
_Q_IMAGE_ESTIMATE_CONFIRM = "Does this look right? You can also type corrections."
_Q_IMAGE_ESTIMATE_EDIT = "Type corrections to the estimate (for example: 'bolt, hex head, length 25, major diameter 5')."

# Metric hex nut defaults (coarse series), keyed by thread major diameter (mm):
# value = (across flats S, thickness M)
_HEX_NUT_SIZE_CHART: dict[float, tuple[float, float]] = {
    2.0: (4.0, 1.6),
    2.5: (5.0, 2.0),
    3.0: (5.5, 2.4),
    4.0: (7.0, 3.2),
    5.0: (8.0, 4.0),
    6.0: (10.0, 5.0),
    8.0: (13.0, 6.5),
    10.0: (17.0, 8.0),
    12.0: (19.0, 10.0),
    14.0: (22.0, 11.0),
    16.0: (24.0, 13.0),
    18.0: (27.0, 15.0),
    20.0: (30.0, 16.0),
    22.0: (32.0, 18.0),
    24.0: (36.0, 19.0),
    27.0: (41.0, 22.0),
    30.0: (46.0, 24.0),
    33.0: (50.0, 26.0),
    36.0: (55.0, 29.0),
    39.0: (60.0, 31.0),
    42.0: (65.0, 34.0),
    48.0: (75.0, 38.0),
}


def _slug(v: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", v).strip("_").lower()


def _unique_output_stem(base: str) -> str:
    base = _slug(base)
    candidate = base
    i = 2
    while True:
        conflicts = [
            _DOWNLOAD_DIR / f"{candidate}.step",
            _DOWNLOAD_DIR / f"{candidate}.stl",
            _DOWNLOAD_DIR / f"{candidate}.svg",
            _DOWNLOAD_DIR / f"{candidate}_drawing.pdf",
            _DOWNLOAD_DIR / f"{candidate}_bundle.zip",
        ]
        if not any(p.exists() for p in conflicts):
            return candidate
        candidate = f"{base}_{i}"
        i += 1


def _solidify_preview_svg(svg_path: Path) -> None:
    """Rewrite CadQuery SVG preview with cleaner CAD-style shading."""
    try:
        text = svg_path.read_text(encoding="utf-8")
    except Exception:
        return

    # Ensure viewBox is present so the SVG scales properly inside <img> tags.
    if "viewBox" not in text:
        w_m = re.search(r'\bwidth="([^"]+)"', text)
        h_m = re.search(r'\bheight="([^"]+)"', text)
        if w_m and h_m:
            vb = f'viewBox="0 0 {w_m.group(1)} {h_m.group(1)}"'
            text = re.sub(r"(<svg\b)", r"\1 " + vb, text, count=1, flags=re.IGNORECASE)

    def _rewrite_path(match: re.Match[str]) -> str:
        tag = match.group(0)
        fill_attr = 'fill="#b0c4cc"'

        # Remove inherited/raw style attributes and apply a consistent style.
        tag = re.sub(r'\sfill="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\sfill-opacity="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\sstroke="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\sstroke-width="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\sstroke-dasharray="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\sstroke-linejoin="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\sstroke-linecap="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\svector-effect="[^"]*"', "", tag, flags=re.IGNORECASE)
        tag = re.sub(r"<path\b", "<path", tag, count=1, flags=re.IGNORECASE)
        tag = tag.replace(
            "<path",
            (
                '<path stroke="#3f4a56" stroke-width="1.05" '
                'stroke-linejoin="round" stroke-linecap="round" '
                f'{fill_attr} vector-effect="non-scaling-stroke"'
            ),
            1,
        )
        return tag

    # Apply per-path styling so open paths are never filled (prevents random
    # triangle artifacts from implicit path closure).
    text = re.sub(r"<path\b[^>]*>", _rewrite_path, text, flags=re.IGNORECASE)

    # Remove style inheritance from groups; paths now carry explicit styles.
    def _clean_group_tag(match: re.Match[str]) -> str:
        gtag = match.group(0)
        gtag = re.sub(r'\sfill="[^"]*"', "", gtag, flags=re.IGNORECASE)
        gtag = re.sub(r'\sstroke="[^"]*"', "", gtag, flags=re.IGNORECASE)
        gtag = re.sub(r'\sstroke-width="[^"]*"', "", gtag, flags=re.IGNORECASE)
        gtag = re.sub(r'\sstroke-dasharray="[^"]*"', "", gtag, flags=re.IGNORECASE)
        return gtag

    text = re.sub(r"<g\b[^>]*>", _clean_group_tag, text, flags=re.IGNORECASE)

    # Remove helper/hidden groups entirely; when filled they create fake
    # diagonal "cut" artifacts across the preview.
    text = re.sub(
        r"<g\b[^>]*stroke-dasharray=\"[^\"]*\"[^>]*>.*?</g>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Remove dashed hidden-edge styling if any leaks through export.
    text = re.sub(
        r'\s+stroke-dasharray="[^"]*"',
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove leaked axis labels from previews.
    text = re.sub(
        r"<text\b[^>]*>.*?</text>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Repair legacy malformed path tags from older rewrites:
    #   <path ... / vector-effect="non-scaling-stroke">
    # -> <path ... vector-effect="non-scaling-stroke"/>
    text = re.sub(
        r'(<path\b[^>]*?)\s+/\s+vector-effect="non-scaling-stroke"\s*>',
        r'\1 vector-effect="non-scaling-stroke"/>',
        text,
        flags=re.IGNORECASE,
    )
    if "vector-effect=" not in text:
        text = re.sub(
            r"(<path\b[^>]*?)(/?)>",
            r'\1 vector-effect="non-scaling-stroke"\2>',
            text,
            flags=re.IGNORECASE,
        )
    try:
        svg_path.write_text(text, encoding="utf-8")
    except Exception:
        return


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


def _user(chat: ChatState, content: str, kind: str = "text", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    msg = {"role": "user", "content": content, "kind": kind}
    if extra:
        msg.update(extra)
    chat.messages.append(msg)
    return msg


def _save_uploaded_image(upload: UploadFile, data: bytes) -> tuple[Path, str]:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        ext = ".png"
    stem = _unique_output_stem(f"upload_{Path(upload.filename or 'image').stem}")
    out_path = _DOWNLOAD_DIR / f"{stem}{ext}"
    out_path.write_bytes(data)
    return out_path, f"/downloads/{out_path.name}"


def _estimate_query_from_image_multimodal(image_path: Path) -> tuple[str, str] | None:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None

    model = (os.getenv("OPENAI_VISION_MODEL") or "gpt-4o-mini").strip()
    base_url = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    try:
        raw = image_path.read_bytes()
    except Exception:
        return None
    mime = "image/png"
    ext = image_path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif ext == ".webp":
        mime = "image/webp"
    elif ext == ".gif":
        mime = "image/gif"
    b64 = base64.b64encode(raw).decode("ascii")
    image_url = f"data:{mime};base64,{b64}"

    system_msg = (
        "You are a fastener-vision estimator. Analyze the image and infer ONE primary fastener only. "
        "Ignore companion hardware such as washers/nuts/background items. "
        "Return ONLY strict JSON with keys: "
        "fastener_type, head_type, drive_type, major_d_mm, length_mm, pitch_mm, confidence, notes. "
        "Allowed fastener_type: screw|bolt. "
        "Allowed head_type: flat|pan|button|hex. "
        "Allowed drive_type: hex|phillips|torx|square|no drive."
    )
    user_msg = (
        "Estimate likely fastener parameters from this photo. "
        "Use realistic metric defaults when unknown. "
        "Do not mention companion hardware."
    )

    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_msg},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    content = ""
    try:
        content = body["choices"][0]["message"]["content"]
    except Exception:
        return None
    if not isinstance(content, str) or not content.strip():
        return None

    text = content.strip()
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        text = m.group(0)
    try:
        est = json.loads(text)
    except Exception:
        return None

    fastener_type = str(est.get("fastener_type", "screw")).strip().lower()
    head_type = str(est.get("head_type", "pan")).strip().lower()
    drive_type = str(est.get("drive_type", "phillips")).strip().lower()
    if fastener_type not in {"screw", "bolt"}:
        fastener_type = "screw"
    if head_type not in {"flat", "pan", "button", "hex"}:
        head_type = "pan"
    if drive_type not in {"hex", "phillips", "torx", "square", "no drive"}:
        drive_type = "no drive"

    def _f(key: str, lo: float, hi: float, fallback: float) -> float:
        try:
            v = float(est.get(key, fallback))
        except Exception:
            v = fallback
        return max(lo, min(hi, v))

    major_d = _f("major_d_mm", 2.0, 12.0, 4.0)
    length = _f("length_mm", 8.0, 120.0, 24.0)
    pitch = _f("pitch_mm", 0.35, 2.5, 0.8)
    head_d = min(max(major_d * 1.35, major_d + 1.2), major_d * 1.65)
    head_h = head_d * (0.42 if head_type == "flat" else 0.52 if head_type == "pan" else 0.48)
    root_d = major_d * (0.84 if fastener_type == "screw" else 0.88)
    thread_h = max(0.2, min(0.9, 0.34 * pitch))
    thread_len = max(0.55 * length, min(0.90 * length, length - 2.0))
    conf = _f("confidence", 0.0, 1.0, 0.55)
    notes = str(est.get("notes", "")).strip()
    query = (
        f"{fastener_type} {head_type} {drive_type} "
        f"head diameter {head_d:.2f} head height {head_h:.2f} "
        f"shank diameter {major_d:.2f} root diameter {root_d:.2f} "
        f"length {length:.2f} pitch {pitch:.2f} thread height {thread_h:.2f} "
        f"thread length {thread_len:.2f}"
    )
    head_label = head_type.title()
    drive_label = drive_type.replace("no drive", "No Drive").title() if drive_type != "no drive" else "None"
    type_label = fastener_type.title()
    summary = (
        f"Here's what I see:\n"
        f"{head_label} head, {drive_label} drive {type_label}\n"
        f"{major_d:.1f} mm diameter, {length:.1f} mm long, {pitch:.2f} mm pitch"
    )
    return query, summary


def _estimate_query_from_image(image_path: Path) -> tuple[str, str]:
    mm = _estimate_query_from_image_multimodal(image_path)
    if mm is not None:
        return mm

    def _fallback_from_size() -> tuple[str, str]:
        w, h = 1024, 768
        try:
            from PIL import Image  # type: ignore

            with Image.open(image_path) as im:
                w, h = im.size
        except Exception:
            pass
        long_side = float(max(w, h))
        short_side = float(max(1, min(w, h)))
        aspect = long_side / short_side
        major_d = 4.0 if long_side < 1200 else 5.0
        fastener_type = "screw" if aspect >= 2.2 else "bolt"
        head_type = "pan" if fastener_type == "screw" else "hex"
        drive_type = "phillips" if fastener_type == "screw" else "no drive"
        length = max(12.0, min(44.0, major_d * aspect * 2.0))
        head_d = min(major_d * 1.55, major_d + 3.0)
        head_h = head_d * (0.42 if head_type == "flat" else 0.52)
        root_d = major_d * 0.84
        pitch = max(0.5, min(1.5, 0.20 * major_d))
        thread_h = max(0.2, min(0.8, 0.35 * pitch))
        thread_len = max(0.55 * length, min(0.85 * length, length - 3.0))
        query = (
            f"{fastener_type} {head_type} {drive_type} "
            f"head diameter {head_d:.2f} head height {head_h:.2f} "
            f"shank diameter {major_d:.2f} root diameter {root_d:.2f} "
            f"length {length:.2f} pitch {pitch:.2f} thread height {thread_h:.2f} "
            f"thread length {thread_len:.2f}"
        )
        head_label = head_type.title()
        drive_label = drive_type.replace("no drive", "No Drive").title() if drive_type != "no drive" else "None"
        type_label = fastener_type.title()
        summary = (
            f"Here's what I see:\n"
            f"{head_label} head, {drive_label} drive {type_label}\n"
            f"{major_d:.1f} mm diameter, {length:.1f} mm long, {pitch:.2f} mm pitch"
        )
        return query, summary

    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        arr = np.fromfile(str(image_path), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            return _fallback_from_size()

        def _clamp(v: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, v))

        def _extract_subject(src):
            h0, w0 = src.shape[:2]
            img_area = float(max(1, h0 * w0))
            gray0 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)

            # If input is a screenshot, first try to isolate the near-square
            # image card by edge geometry.
            edge_card = None
            edges0 = cv2.Canny(gray0, 60, 160)
            edges0 = cv2.dilate(edges0, np.ones((3, 3), np.uint8), iterations=1)
            card_edges, _ = cv2.findContours(edges0, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            best_edge_score = -1.0
            for c in card_edges:
                area = float(cv2.contourArea(c))
                if area < 0.03 * img_area or area > 0.92 * img_area:
                    continue
                x, y, bw, bh = cv2.boundingRect(c)
                if bw <= 0 or bh <= 0:
                    continue
                ar = bw / float(max(1, bh))
                if ar < 0.70 or ar > 1.45:
                    continue
                peri = cv2.arcLength(c, True)
                approx = cv2.approxPolyDP(c, 0.02 * peri, True)
                if len(approx) < 4 or len(approx) > 10:
                    continue
                cx = x + 0.5 * bw
                cy = y + 0.5 * bh
                center_penalty = math.hypot(cx - 0.5 * w0, cy - 0.5 * h0) / max(w0, h0)
                square_penalty = abs(math.log(max(ar, 1.0 / max(ar, 1e-6))))
                fill = area / float(max(1, bw * bh))
                score = (area / img_area) + 0.35 * fill - 1.15 * center_penalty - 0.75 * square_penalty
                if score > best_edge_score:
                    best_edge_score = score
                    edge_card = (x, y, bw, bh)
            if edge_card is not None:
                x, y, bw, bh = edge_card
                pad = max(5, int(0.02 * min(bw, bh)))
                x0 = max(0, x + pad)
                y0 = max(0, y + pad)
                x1 = min(w0, x + bw - pad)
                y1 = min(h0, y + bh - pad)
                if (x1 - x0) > 60 and (y1 - y0) > 60:
                    src = src[y0:y1, x0:x1]
                    gray0 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
                    h0, w0 = src.shape[:2]

            # Then try bright-card extraction as a secondary screenshot pass.
            white = (gray0 > 236).astype(np.uint8) * 255
            white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
            card_cnts, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            img_area = float(max(1, h0 * w0))
            best_card = None
            best_card_score = -1.0

            def _scan_cards(prefer_square: bool) -> tuple[tuple[int, int, int, int] | None, float]:
                local_best = None
                local_best_score = -1.0
                for c in card_cnts:
                    area = float(cv2.contourArea(c))
                    if area < 0.02 * img_area or area > 0.88 * img_area:
                        continue
                    x, y, bw, bh = cv2.boundingRect(c)
                    if bw <= 0 or bh <= 0:
                        continue
                    ar = bw / float(max(1, bh))
                    if prefer_square:
                        if ar < 0.72 or ar > 1.45:
                            continue
                    elif ar < 0.42 or ar > 2.1:
                        continue
                    cx = x + 0.5 * bw
                    cy = y + 0.5 * bh
                    center_penalty = math.hypot(cx - 0.5 * w0, cy - 0.5 * h0) / max(w0, h0)
                    square_penalty = abs(math.log(max(ar, 1.0 / max(ar, 1e-6))))
                    area_frac = area / img_area
                    score = area_frac - 1.35 * center_penalty - (0.70 * square_penalty if prefer_square else 0.18 * square_penalty)
                    if score > local_best_score:
                        local_best_score = score
                        local_best = (x, y, bw, bh)
                return local_best, local_best_score

            best_card, best_card_score = _scan_cards(prefer_square=True)
            if best_card is None:
                best_card, best_card_score = _scan_cards(prefer_square=False)
            if best_card is not None:
                x, y, bw, bh = best_card
                pad = 5
                x0 = max(0, x + pad)
                y0 = max(0, y + pad)
                x1 = min(w0, x + bw - pad)
                y1 = min(h0, y + bh - pad)
                if (x1 - x0) > 40 and (y1 - y0) > 40:
                    src = src[y0:y1, x0:x1]
                    gray0 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)

            def _extract_from(src_in):
                h1, w1 = src_in.shape[:2]
                border = np.concatenate([src_in[0, :, :], src_in[-1, :, :], src_in[:, 0, :], src_in[:, -1, :]], axis=0).astype(
                    np.float32
                )
                bg = np.median(border, axis=0)
                diff = np.linalg.norm(src_in.astype(np.float32) - bg[None, None, :], axis=2)
                thr = max(20.0, float(np.percentile(diff, 83)))
                mask = (diff > thr).astype(np.uint8) * 255
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not cnts:
                    return None

                def _score_contour(c):
                    area = float(cv2.contourArea(c))
                    if area <= 0:
                        return -1.0e9
                    x, y, bw, bh = cv2.boundingRect(c)
                    if bw <= 0 or bh <= 0:
                        return -1.0e9
                    area_frac = area / float(max(1, w1 * h1))
                    if area_frac < 0.0012 or area_frac > 0.70:
                        return -1.0e9
                    rect = cv2.minAreaRect(c)
                    rw, rh = rect[1]
                    elong = max(rw, rh) / max(1.0, min(rw, rh))
                    fill = area / float(max(1, bw * bh))
                    cx = x + 0.5 * bw
                    cy = y + 0.5 * bh
                    center = math.hypot(cx - 0.5 * w1, cy - 0.5 * h1) / max(w1, h1)
                    border_touch = x <= 1 or y <= 1 or (x + bw) >= (w1 - 1) or (y + bh) >= (h1 - 1)
                    return 2.4 * elong + 0.7 * math.sqrt(area_frac) - 1.5 * fill - 1.1 * center - (1.6 if border_touch else 0.0)

                cnt = max(cnts, key=_score_contour)
                best_score = _score_contour(cnt)
                if cv2.contourArea(cnt) < 0.0012 * (w1 * h1):
                    return None
                x, y, bw, bh = cv2.boundingRect(cnt)
                pad = 8
                x0 = max(0, x - pad)
                y0 = max(0, y - pad)
                x1 = min(w1, x + bw + pad)
                y1 = min(h1, y + bh + pad)
                return src_in[y0:y1, x0:x1], mask[y0:y1, x0:x1], cnt, float(best_score)

            picked = _extract_from(src)
            # Screenshot card detection can occasionally over-crop; keep a raw
            # full-image path and take whichever contour score is stronger.
            if src.shape != img.shape:
                raw_pick = _extract_from(img)
                if raw_pick is not None and (picked is None or raw_pick[3] > picked[3] + 0.15):
                    picked = raw_pick
            if picked is None:
                return None
            return picked[0], picked[1], picked[2]

        extracted = _extract_subject(img)
        if extracted is None:
            return _fallback_from_size()
        crop, crop_mask, cnt = extracted

        pts = cv2.findNonZero(crop_mask)
        if pts is None:
            return _fallback_from_size()
        rect = cv2.minAreaRect(pts)
        rw, rh = rect[1]
        angle = rect[2] + (90.0 if rw < rh else 0.0)
        M = cv2.getRotationMatrix2D((crop.shape[1] / 2, crop.shape[0] / 2), angle, 1.0)
        rot = cv2.warpAffine(crop, M, (crop.shape[1], crop.shape[0]), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
        rot_mask = cv2.warpAffine(crop_mask, M, (crop.shape[1], crop.shape[0]), flags=cv2.INTER_NEAREST, borderValue=0)
        pts2 = cv2.findNonZero(rot_mask)
        if pts2 is None:
            return _fallback_from_size()
        x2, y2, bw2, bh2 = cv2.boundingRect(pts2)
        rot = rot[y2 : y2 + bh2, x2 : x2 + bw2]
        rot_mask = rot_mask[y2 : y2 + bh2, x2 : x2 + bw2]

        raw_prof = (rot_mask > 0).sum(axis=0).astype(np.float32)
        if raw_prof.size < 24:
            return _fallback_from_size()
        prof = np.convolve(raw_prof, np.ones(9, dtype=np.float32) / 9.0, mode="same")
        n = prof.size

        edge_span = max(4, n // 9)
        left_peak = float(np.max(prof[:edge_span]))
        right_peak = float(np.max(prof[-edge_span:]))
        left_mean = float(np.mean(prof[:edge_span]))
        right_mean = float(np.mean(prof[-edge_span:]))
        head_left = (left_peak + 0.2 * left_mean) >= (right_peak + 0.2 * right_mean)

        shaft_slice = prof[int(0.30 * n) : int(0.70 * n)]
        shaft_pos = shaft_slice[shaft_slice > 0]
        shaft_w = float(np.median(shaft_pos)) if shaft_pos.size > 0 else float(np.median(prof))
        shaft_w = max(shaft_w, 1.0)

        tail_arr = prof[-max(4, n // 22) :] if head_left else prof[: max(4, n // 22)]
        tip_ratio = float(np.mean(tail_arr)) / shaft_w
        tail_span = max(8, n // 6)
        tail_from_shaft = prof[-tail_span:] if head_left else prof[:tail_span][::-1]
        t0 = float(np.mean(tail_from_shaft[: max(2, tail_span // 3)]))
        t1 = float(np.mean(tail_from_shaft[-max(2, tail_span // 3) :]))
        tip_taper = _clamp((t0 - t1) / max(1.0, shaft_w), 0.0, 1.5)

        arr_head = prof if head_left else prof[::-1]
        thr = 1.22 * shaft_w
        max_scan = max(8, min(int(0.45 * n), n - 1))
        head_len = None
        for i in range(4, max_scan):
            local = float(np.mean(arr_head[max(0, i - 2) : i + 1]))
            if arr_head[i] <= 1.10 * shaft_w and local <= 1.13 * shaft_w:
                head_len = i
                break
        if head_len is None:
            for i, v in enumerate(arr_head[:max_scan]):
                if v < thr:
                    head_len = i
                    break
        head_len = max(1, int(head_len) if head_len is not None else int(0.16 * n))
        head_zone = arr_head[: max(6, head_len)]
        head_ratio = float(np.max(head_zone)) / shaft_w
        idx_tail = min(head_zone.size - 1, max(2, int(0.65 * head_zone.size)))
        head_drop = float(np.max(head_zone) - head_zone[idx_tail]) / shaft_w
        corr = 0.0
        if head_zone.size >= 8:
            xh = np.arange(head_zone.size, dtype=np.float32)
            corr = abs(float(np.corrcoef(xh, head_zone)[0, 1]))
        head_len_ratio = head_len / shaft_w

        shaft_band = raw_prof[int(0.25 * n) : int(0.90 * n)]
        roughness = float(np.std(np.diff(shaft_band))) / shaft_w if shaft_band.size >= 12 else 0.0

        rect_cnt = cv2.minAreaRect(cnt)
        rw_cnt, rh_cnt = rect_cnt[1]
        contour_elong = max(rw_cnt, rh_cnt) / max(1.0, min(rw_cnt, rh_cnt))

        screw_score = 0.0
        bolt_score = 0.0
        screw_score += max(0.0, 0.57 - tip_ratio) * 2.4
        bolt_score += max(0.0, tip_ratio - 0.58) * 1.6
        screw_score += min(1.35, roughness * 9.5)
        screw_score += min(0.95, max(0.0, contour_elong - 2.1) * 0.42)
        if tip_ratio < 0.46:
            screw_score += 0.65
        if tip_ratio > 0.68:
            bolt_score += 0.45
        if roughness > 0.11:
            screw_score += 0.35
        if contour_elong > 3.0:
            screw_score += 0.20
        if tip_taper > 0.24:
            screw_score += 0.48
        if tip_taper < 0.08:
            bolt_score += 0.38
        fastener_type = "screw" if screw_score >= bolt_score else "bolt"
        type_conf = _clamp(abs(screw_score - bolt_score) / max(1.0, screw_score + bolt_score), 0.0, 0.99)

        # Countersunk/flat heads produce a stronger profile drop and taper than
        # pan/button in side view.
        head_taper = 0.0
        if head_zone.size >= 8:
            left_h = float(np.mean(head_zone[: max(2, head_zone.size // 4)]))
            right_h = float(np.mean(head_zone[-max(2, head_zone.size // 4) :]))
            head_taper = max(0.0, left_h - right_h) / max(1.0, shaft_w)

        flat_score = 0.0
        pan_score = 0.0
        button_score = 0.0
        flat_score += max(0.0, head_ratio - 1.24) * 1.6
        flat_score += max(0.0, head_drop - 0.10) * 3.0
        flat_score += max(0.0, head_taper - 0.10) * 2.2
        if head_len_ratio < 1.25:
            flat_score += 0.5
        if corr > 0.45:
            flat_score += 0.35
        if contour_elong > 2.4:
            flat_score += 0.20
        pan_score += max(0.0, head_ratio - 1.18) * 1.3
        pan_score += max(0.0, 1.6 - head_len_ratio) * 0.5
        if head_drop < 0.14:
            pan_score += 0.35
        if head_taper < 0.07:
            pan_score += 0.18
        button_score += max(0.0, 1.28 - head_ratio) * 1.1
        button_score += max(0.0, head_len_ratio - 0.9) * 0.25
        if head_drop < 0.08:
            button_score += 0.35

        if flat_score >= pan_score and flat_score >= button_score:
            head_type = "flat"
            head_conf = _clamp(flat_score / max(1.0, flat_score + pan_score + button_score), 0.0, 0.99)
        elif pan_score >= button_score:
            head_type = "pan"
            head_conf = _clamp(pan_score / max(1.0, flat_score + pan_score + button_score), 0.0, 0.99)
        else:
            head_type = "button"
            head_conf = _clamp(button_score / max(1.0, flat_score + pan_score + button_score), 0.0, 0.99)

        drive_type = "no drive"
        drive_conf = 0.0
        drive_hv = 0
        drive_diag = 0
        drive_verts = 0
        drive_fine_verts = 0
        drive_diamond = 0.0
        drive_dir_div = 0
        drive_lobes = 0
        drive_solidity = 1.0
        drive_shape_ph = 0.0
        drive_shape_sq = 0.0
        drive_shape_tx = 0.0
        # Keep drive analysis tightly around the head; including too much shaft
        # introduces thread lines that look like false drive strokes.
        head_width_px = int(min(rot.shape[1], max(22, round(max(1.15 * head_len, 0.14 * n)))))
        head_roi = rot[:, :head_width_px] if head_left else rot[:, -head_width_px:]
        gray = cv2.cvtColor(head_roi, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        eq = clahe.apply(gray)
        dark = (eq < np.percentile(eq, 30)).astype(np.uint8) * 255
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            hroi, wroi = dark.shape[:2]
            cx, cy = 0.5 * wroi, 0.5 * hroi
            near_center: list[Any] = []
            roi_diag = max(1.0, math.hypot(wroi, hroi))
            for c in cnts:
                area = float(cv2.contourArea(c))
                if area < 8:
                    continue
                m = cv2.moments(c)
                if m["m00"] <= 0:
                    continue
                xcc = m["m10"] / m["m00"]
                ycc = m["m01"] / m["m00"]
                d_norm = math.hypot(xcc - cx, ycc - cy) / roi_diag
                if d_norm <= 0.40:
                    near_center.append(c)
            best = None
            if near_center:
                comb = np.zeros((hroi, wroi), dtype=np.uint8)
                cv2.drawContours(comb, near_center, -1, 255, thickness=-1)
                comb = cv2.morphologyEx(comb, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
                ccnts, _ = cv2.findContours(comb, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if ccnts:
                    best = max(ccnts, key=cv2.contourArea)
            if best is None:
                best_score = -1.0
                for c in cnts:
                    area = float(cv2.contourArea(c))
                    if area < 14:
                        continue
                    m = cv2.moments(c)
                    if m["m00"] <= 0:
                        continue
                    xcc = m["m10"] / m["m00"]
                    ycc = m["m01"] / m["m00"]
                    d = math.hypot(xcc - cx, ycc - cy)
                    score = area - 0.9 * d
                    if score > best_score:
                        best_score = score
                        best = c
            if best is not None:
                best_area = float(cv2.contourArea(best))
                peri = cv2.arcLength(best, True)
                approx = cv2.approxPolyDP(best, 0.05 * peri, True)
                approx_fine = cv2.approxPolyDP(best, 0.02 * peri, True)
                verts = len(approx)
                drive_verts = verts
                drive_fine_verts = len(approx_fine)
                edges = cv2.Canny(eq, 65, 145)
                lines = cv2.HoughLinesP(edges, 1, np.pi / 180.0, threshold=20, minLineLength=9, maxLineGap=4)
                hv = 0
                diag = 0
                dir_bins: set[int] = set()
                if lines is not None:
                    for ln in lines[:, 0, :]:
                        x1, y1, x2, y2 = ln
                        ang = abs(math.degrees(math.atan2(y2 - y1, x2 - x1)))
                        ang = min(ang, 180.0 - ang)
                        dir_bins.add(int(ang // 15))
                        if ang < 15 or abs(ang - 90.0) < 15:
                            hv += 1
                        if abs(ang - 45.0) < 16:
                            diag += 1
                drive_hv = hv
                drive_diag = diag
                drive_dir_div = len(dir_bins)

                # Directional occupancy around the recess center is more stable
                # than line-only detection under blur/perspective.
                x, y, bw, bh = cv2.boundingRect(best)
                cxi = int(x + 0.5 * bw)
                cyi = int(y + 0.5 * bh)
                xb0 = max(0, cxi - 1)
                xb1 = min(wroi, cxi + 2)
                yb0 = max(0, cyi - 1)
                yb1 = min(hroi, cyi + 2)
                v_band = dark[:, xb0:xb1]
                h_band = dark[yb0:yb1, :]
                v_occ = float(np.mean(np.sum(v_band > 0, axis=0))) / max(1.0, float(hroi))
                h_occ = float(np.mean(np.sum(h_band > 0, axis=1))) / max(1.0, float(wroi))
                cross_occ = 0.5 * (v_occ + h_occ)
                area_ratio = best_area / max(1.0, float(hroi * wroi))
                rect_b = cv2.minAreaRect(best)
                rw_b, rh_b = rect_b[1]
                box_aspect = max(rw_b, rh_b) / max(1.0, min(rw_b, rh_b))
                ang_b = abs(float(rect_b[2]))
                if ang_b > 90.0:
                    ang_b = 180.0 - ang_b
                hull = cv2.convexHull(best)
                hull_area = float(cv2.contourArea(hull))
                solidity = best_area / max(hull_area, 1.0)
                drive_solidity = solidity
                # Diamond-shaped square recesses often sit around ~45 deg.
                diamond_bonus = 0.0
                if 0.82 <= (1.0 / max(1.0, box_aspect) if box_aspect > 1.0 else box_aspect) <= 1.0:
                    if 28.0 <= ang_b <= 62.0:
                        diamond_bonus = 0.80
                drive_diamond = diamond_bonus
                corner_bonus = 0.24 if 4 <= verts <= 6 else 0.0
                lobe_bonus = 0.0
                shape_ph = 0.0
                shape_sq = 0.0
                shape_tx = 0.0
                try:
                    pts = best[:, 0, :].astype(np.float32)
                    angs = np.arctan2(pts[:, 1] - cyi, pts[:, 0] - cxi)
                    angs = (angs + 2.0 * np.pi) % (2.0 * np.pi)
                    rad = np.hypot(pts[:, 0] - cxi, pts[:, 1] - cyi)
                    n_bins = 36
                    bins = np.floor((angs / (2.0 * np.pi)) * n_bins).astype(np.int32)
                    ring = np.zeros(n_bins, dtype=np.float32)
                    for bi, rv in zip(bins, rad):
                        bi = int(max(0, min(n_bins - 1, bi)))
                        if rv > ring[bi]:
                            ring[bi] = float(rv)
                    ring = np.convolve(
                        np.r_[ring[-1], ring, ring[0]],
                        np.array([0.25, 0.5, 0.25], dtype=np.float32),
                        mode="same",
                    )[1:-1]
                    mean_ring = float(np.mean(ring)) if ring.size else 0.0
                    lobes = 0
                    for i in range(n_bins):
                        a = ring[(i - 1) % n_bins]
                        b = ring[i]
                        c = ring[(i + 1) % n_bins]
                        if b > a and b > c and b > (1.06 * mean_ring):
                            lobes += 1
                    drive_lobes = lobes
                    if lobes >= 5:
                        lobe_bonus = 0.32 * min(3, lobes - 4)
                except Exception:
                    pass
                try:
                    patch = dark[max(0, y) : min(hroi, y + bh), max(0, x) : min(wroi, x + bw)]
                    if patch.size > 0:
                        patch = cv2.resize(patch, (64, 64), interpolation=cv2.INTER_NEAREST)
                        patch = (patch > 0).astype(np.uint8) * 255

                        def _tmpl(kind: str) -> np.ndarray:
                            t = np.zeros((64, 64), dtype=np.uint8)
                            c = (32, 32)
                            if kind == "ph":
                                cv2.rectangle(t, (28, 12), (36, 52), 255, -1)
                                cv2.rectangle(t, (12, 28), (52, 36), 255, -1)
                            elif kind == "sq":
                                cv2.rectangle(t, (18, 18), (46, 46), 255, -1)
                            else:
                                pts_star = []
                                for i in range(12):
                                    a = (i / 12.0) * 2.0 * math.pi - math.pi / 2.0
                                    r = 21 if i % 2 == 0 else 11
                                    pts_star.append([int(c[0] + r * math.cos(a)), int(c[1] + r * math.sin(a))])
                                cv2.fillPoly(t, [np.array(pts_star, dtype=np.int32)], 255)
                            return t

                        def _corr(a: np.ndarray, b: np.ndarray) -> float:
                            af = a.astype(np.float32).reshape(-1)
                            bf = b.astype(np.float32).reshape(-1)
                            af -= float(np.mean(af))
                            bf -= float(np.mean(bf))
                            den = float(np.linalg.norm(af) * np.linalg.norm(bf))
                            if den <= 1e-6:
                                return 0.0
                            return float(np.dot(af, bf) / den)

                        shape_ph = _corr(patch, _tmpl("ph"))
                        shape_sq = _corr(patch, _tmpl("sq"))
                        shape_tx = _corr(patch, _tmpl("tx"))
                        drive_shape_ph = shape_ph
                        drive_shape_sq = shape_sq
                        drive_shape_tx = shape_tx
                except Exception:
                    pass

                center_r = max(4, int(0.11 * min(wroi, hroi)))
                c0x = max(0, cxi - center_r)
                c1x = min(wroi, cxi + center_r + 1)
                c0y = max(0, cyi - center_r)
                c1y = min(hroi, cyi + center_r + 1)
                center_patch = eq[c0y:c1y, c0x:c1x]
                bg_patch = eq[max(0, c0y - center_r) : min(hroi, c1y + center_r), max(0, c0x - center_r) : min(wroi, c1x + center_r)]
                center_dark_delta = 0.0
                if center_patch.size > 0 and bg_patch.size > 0:
                    center_dark_delta = float(np.mean(bg_patch) - np.mean(center_patch))
                best_center_dist = math.hypot(cxi - cx, cyi - cy) / max(1.0, 0.5 * math.hypot(wroi, hroi))
                has_recess = (
                    best_center_dist < 0.62
                    and area_ratio >= 0.003
                    and (center_dark_delta >= 2.0 or cross_occ >= 0.05)
                )
                # Very low solidity (star/torx shape) is strong evidence even
                # when the center delta is negative due to specular highlights.
                if not has_recess and best_center_dist < 0.65 and solidity < 0.58 and area_ratio >= 0.003:
                    has_recess = True
                ph_score = 0.48 * hv + 1.05 * cross_occ + (0.22 if verts > 6 else 0.0)
                sq_score = 0.82 * diag + 0.78 * area_ratio + corner_bonus + diamond_bonus
                tx_score = (
                    0.35 * min(hv, diag)
                    + 0.18 * max(0, verts - 6)
                    + 0.14 * max(0, len(approx_fine) - 7)
                    + 1.1 * max(0.0, 0.93 - solidity)
                    + 0.35 * area_ratio
                    + 0.22 * max(0, len(dir_bins) - 2)
                    + lobe_bonus
                    + (0.25 if 0.82 <= (1.0 / max(1.0, box_aspect) if box_aspect > 1.0 else box_aspect) <= 1.0 else 0.0)
                )
                ph_score += 0.9 * max(0.0, shape_ph - 0.15)
                sq_score += 0.9 * max(0.0, shape_sq - 0.15)
                tx_score += 1.1 * max(0.0, shape_tx - 0.12)
                if has_recess and tx_score >= 1.25 and tx_score >= sq_score + 0.15 and tx_score >= ph_score - 0.08:
                    drive_type = "torx"
                    drive_conf = _clamp(tx_score / max(3.0, ph_score + sq_score + tx_score), 0.0, 0.99)
                elif has_recess and ph_score >= 1.30 and hv >= 3 and ph_score >= sq_score:
                    drive_type = "phillips"
                    drive_conf = _clamp(ph_score / max(2.8, ph_score + sq_score), 0.0, 0.99)
                elif has_recess and sq_score >= 0.88:
                    drive_type = "square"
                    drive_conf = _clamp(sq_score / max(2.8, ph_score + sq_score), 0.0, 0.99)
                else:
                    drive_type = "no drive"
                    drive_conf = _clamp(1.0 - max(ph_score, sq_score) / 2.5, 0.15, 0.95)

        if type_conf < 0.45 and contour_elong > 2.2 and tip_ratio < 0.62:
            fastener_type = "screw"
            type_conf = _clamp(type_conf + 0.18, 0.0, 0.99)
        # Template-backed drive evidence strongly favours screw over bolt.
        if fastener_type == "bolt" and drive_type in {"phillips", "torx", "square"} and max(drive_shape_ph, drive_shape_sq, drive_shape_tx) > 0.10:
            fastener_type = "screw"
            type_conf = _clamp(max(type_conf, 0.55), 0.0, 0.99)
        if head_conf < 0.55 and fastener_type == "screw" and drive_type == "phillips" and head_ratio > 1.18:
            head_type = "flat"
            head_conf = _clamp(head_conf + 0.18, 0.0, 0.99)
        if type_conf < 0.40 and drive_type == "phillips":
            fastener_type = "screw"
            type_conf = _clamp(type_conf + 0.22, 0.0, 0.99)
        if head_conf < 0.50 and fastener_type == "screw" and drive_type == "phillips" and head_ratio > 1.12:
            head_type = "flat"
            head_conf = _clamp(head_conf + 0.22, 0.0, 0.99)
        if head_conf < 0.50 and fastener_type == "screw" and drive_type == "phillips":
            head_type = "flat"
            head_conf = _clamp(head_conf + 0.16, 0.0, 0.99)
        if (
            drive_type == "square"
            and fastener_type == "screw"
            and head_type != "flat"
            and (head_conf < 0.65 or head_taper > 0.10)
            and head_ratio > 1.16
        ):
            head_type = "flat"
            head_conf = _clamp(max(head_conf, 0.58), 0.0, 0.99)
        if drive_type == "square" and fastener_type == "screw" and head_type != "flat" and head_conf < 0.50:
            head_type = "flat"
            head_conf = _clamp(max(head_conf, 0.56), 0.0, 0.99)
        if drive_type == "square" and head_type == "flat" and type_conf < 0.70:
            fastener_type = "screw"
            type_conf = _clamp(max(type_conf, 0.62), 0.0, 0.99)
        if drive_type == "phillips" and drive_diag >= max(2, drive_hv) and drive_verts <= 6:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.58), 0.0, 0.99)
        if drive_type == "phillips" and drive_diamond >= 0.45 and drive_verts <= 6:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.60), 0.0, 0.99)
        if drive_type == "phillips" and head_type == "flat" and drive_conf < 0.78 and drive_verts <= 8:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.56), 0.0, 0.99)
        if (
            drive_type == "phillips"
            and drive_shape_sq > drive_shape_ph
            and drive_shape_sq > 0.10
            and ph_score < sq_score * 6
        ):
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.58), 0.0, 0.99)
        if drive_type == "phillips" and drive_solidity > 0.80 and drive_verts <= 5:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.55), 0.0, 0.99)
        if drive_type == "phillips" and head_type in {"pan", "button"} and drive_verts >= 8 and drive_hv >= 2 and drive_diag >= 1 and drive_hv < 25:
            drive_type = "torx"
            drive_conf = _clamp(max(drive_conf, 0.58), 0.0, 0.99)
        if drive_type == "phillips" and head_type in {"pan", "button"} and drive_dir_div >= 4 and drive_diag >= 1 and drive_hv < 25:
            drive_type = "torx"
            drive_conf = _clamp(max(drive_conf, 0.56), 0.0, 0.99)
        if drive_type == "phillips" and head_type in {"pan", "button"} and drive_fine_verts >= 8 and drive_diag >= 1 and drive_hv < 25:
            drive_type = "torx"
            drive_conf = _clamp(max(drive_conf, 0.57), 0.0, 0.99)
        if drive_type == "phillips" and head_type in {"pan", "button"} and drive_lobes >= 5:
            drive_type = "torx"
            drive_conf = _clamp(max(drive_conf, 0.60), 0.0, 0.99)
        # Very low solidity (star-shaped contour) is the strongest torx signal;
        # require >= 5 coarse vertices to avoid triangular shadow artefacts.
        if drive_type == "phillips" and drive_solidity < 0.58 and drive_verts >= 5:
            drive_type = "torx"
            drive_conf = _clamp(max(drive_conf, 0.62), 0.0, 0.99)
        # Torx → Square overrides: square recesses are more solid and have
        # fewer vertices than torx star patterns.
        if drive_type == "torx" and drive_solidity >= 0.72 and drive_verts <= 6:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.60), 0.0, 0.99)
        if drive_type == "torx" and drive_shape_sq > drive_shape_tx and drive_shape_sq > 0.10:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.58), 0.0, 0.99)
        if drive_type == "torx" and head_type == "flat" and drive_solidity >= 0.60 and drive_verts <= 8:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.56), 0.0, 0.99)
        if drive_type == "torx" and drive_diamond >= 0.40 and drive_verts <= 6:
            drive_type = "square"
            drive_conf = _clamp(max(drive_conf, 0.62), 0.0, 0.99)
        # Head refinements that depend on the final drive classification.
        if (
            fastener_type == "screw"
            and drive_type in {"phillips", "square"}
            and head_type != "flat"
            and head_drop > 0.11
        ):
            head_type = "flat"
            head_conf = _clamp(max(head_conf, 0.52), 0.0, 0.99)
        # Strong head taper means flat/countersunk — override bolt/hex.
        if head_taper >= 0.10 and head_type != "flat":
            head_type = "flat"
            head_conf = _clamp(max(head_conf, 0.60), 0.0, 0.99)
        if head_taper >= 0.10 and fastener_type == "bolt":
            fastener_type = "screw"
            type_conf = _clamp(max(type_conf, 0.58), 0.0, 0.99)
        if drive_type == "no drive" and tip_ratio > 0.66 and type_conf < 0.72 and head_taper < 0.08:
            fastener_type = "bolt"
            type_conf = _clamp(max(type_conf, 0.64), 0.0, 0.99)
        if fastener_type == "bolt" and drive_type == "no drive" and head_conf < 0.80 and head_taper < 0.08:
            head_type = "hex"
            head_conf = _clamp(max(head_conf, 0.66), 0.0, 0.99)

        obj_len_px = float(n)
        rel = shaft_w / max(obj_len_px, 1.0)
        major_cont = _clamp(rel * 26.0, 2.2, 7.0)
        if contour_elong > 2.8:
            major_cont = _clamp(major_cont * 0.88, 2.0, 6.0)
        common = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 8.0]
        major_d = min(common, key=lambda d: abs(d - major_cont))
        length = _clamp(major_d * _clamp((obj_len_px / max(shaft_w, 1.0)) * 0.62, 2.4, 8.8), 8.0, 90.0)
        if drive_type == "no drive" and major_d >= 5.5 and (length / max(major_d, 1e-6)) < 3.3 and head_taper < 0.08:
            fastener_type = "bolt"
            type_conf = _clamp(max(type_conf, 0.66), 0.0, 0.99)
            if head_conf < 0.82:
                head_type = "hex"
                head_conf = _clamp(max(head_conf, 0.68), 0.0, 0.99)
        # Only force bolt/hex/no-drive when no template evidence supports the
        # current drive classification (avoids stripping a real phillips/torx/
        # square on a short thick screw photographed at an angle).
        _has_template_evidence = max(drive_shape_ph, drive_shape_sq, drive_shape_tx) > 0.10
        if major_d >= 5.5 and (length / max(major_d, 1e-6)) < 3.3 and head_ratio > 1.22 and not _has_template_evidence and head_taper < 0.08:
            fastener_type = "bolt"
            head_type = "hex"
            drive_type = "no drive"
            type_conf = _clamp(max(type_conf, 0.68), 0.0, 0.99)
            head_conf = _clamp(max(head_conf, 0.70), 0.0, 0.99)
            drive_conf = _clamp(max(drive_conf, 0.60), 0.0, 0.99)
        if major_d >= 5.5 and (length / max(major_d, 1e-6)) < 3.0 and drive_type == "phillips" and not _has_template_evidence and head_taper < 0.08:
            fastener_type = "bolt"
            head_type = "hex"
            drive_type = "no drive"
            type_conf = _clamp(max(type_conf, 0.70), 0.0, 0.99)
            head_conf = _clamp(max(head_conf, 0.72), 0.0, 0.99)
            drive_conf = _clamp(max(drive_conf, 0.62), 0.0, 0.99)

        def _coarse_pitch(d: float) -> float:
            if d <= 3.0:
                return 0.50
            if d <= 4.0:
                return 0.70
            if d <= 5.0:
                return 0.80
            if d <= 6.0:
                return 1.00
            if d <= 8.0:
                return 1.25
            return 1.50

        pitch = _coarse_pitch(major_d)
        head_d = _clamp(max(major_d * 1.28, head_ratio * major_d * 0.90), major_d * 1.22, major_d * 1.62)
        head_h = head_d * (0.42 if head_type == "flat" else 0.52 if head_type == "pan" else 0.48)
        root_d = major_d * (0.84 if fastener_type == "screw" else 0.88)
        thread_h = _clamp(0.34 * pitch, 0.2, 0.85)
        thread_len = _clamp(length * 0.74, 0.55 * length, length - 2.5)

        query = (
            f"{fastener_type} {head_type} {drive_type} "
            f"head diameter {head_d:.2f} head height {head_h:.2f} "
            f"shank diameter {major_d:.2f} root diameter {root_d:.2f} "
            f"length {length:.2f} pitch {pitch:.2f} thread height {thread_h:.2f} "
            f"thread length {thread_len:.2f}"
        )
        head_label = head_type.title()
        drive_label = "None" if drive_type == "no drive" else drive_type.title()
        type_label = fastener_type.title()
        summary = (
            f"Here's what I see:\n"
            f"{head_label} head, {drive_label} drive {type_label}\n"
            f"{major_d:.1f} mm diameter, {length:.1f} mm long, {pitch:.2f} mm pitch"
        )
        return query, summary
    except Exception:
        return _fallback_from_size()


def _chat_title_for_spec(spec) -> str:
    threadish = any(isinstance(r, ThreadRegionSpec) for r in spec.regions)
    kind = "Bolt" if spec.fastener_type == "bolt" else "Screw"
    drive = spec.drive.type.title() if spec.drive else "No Drive"
    head = spec.head.type.title()
    d = spec.shaft.d_minor
    L = spec.shaft.L
    parts = [head, drive, f"{'Threaded ' if threadish else ''}{kind}"]
    return f"{' '.join(parts)} ({d:.1f} x {L:.1f} mm)"


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
    elif drive == "square":
        s = top_r * 0.50
        drive_glyph = f'<rect x="{top_cx - s/2:.1f}" y="{top_cy - s/2:.1f}" width="{s:.1f}" height="{s:.1f}" class="ink" fill="none"/>'

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

    author = (author_name or os.getenv("DRAWING_AUTHOR", "") or "User").strip() or "User"
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
    elif drive == "square":
        s = top_r * 0.62
        c.rect(top_cx - s / 2.0, top_cy - s / 2.0, s, s, stroke=1, fill=0)
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

    def _dim_h_arrow(x1: float, x2: float, y: float, ext_y1: float, ext_y2: float, label: str) -> None:
        c.setLineWidth(1)
        c.line(x1, ext_y1, x1, y)
        c.line(x2, ext_y2, x2, y)
        c.line(x1, y, x2, y)
        ah = 6.0
        aw = 2.6
        c.line(x1, y, x1 + ah, y + aw)
        c.line(x1, y, x1 + ah, y - aw)
        c.line(x2, y, x2 - ah, y + aw)
        c.line(x2, y, x2 - ah, y - aw)
        c.setFont("Helvetica", 9)
        c.drawString((x1 + x2) / 2 - 20, y + 4, label)

    def _dim_v_arrow(x: float, y1: float, y2: float, ext_x1: float, ext_x2: float, label: str) -> None:
        c.setLineWidth(1)
        c.line(ext_x1, y1, x, y1)
        c.line(ext_x2, y2, x, y2)
        c.line(x, y1, x, y2)
        ah = 6.0
        aw = 2.6
        c.line(x, y1, x - aw, y1 + ah)
        c.line(x, y1, x + aw, y1 + ah)
        c.line(x, y2, x - aw, y2 - ah)
        c.line(x, y2, x + aw, y2 - ah)
        c.setFont("Helvetica", 9)
        c.drawString(x + 8, (y1 + y2) / 2 - 3, label)

    margin = 18
    ix, iy = margin, margin
    iw, ih = page_w - 2 * margin, page_h - 2 * margin
    c.rect(ix, iy, iw, ih, stroke=1, fill=0)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(ix + 16, iy + ih - 24, "Nut Engineering Drawing")
    c.setFont("Helvetica", 9)
    c.drawString(ix + 16, iy + ih - 38, f"Part: Matching {style_name} Nut")

    # Larger top/side views aligned on one centerline to use page better.
    view_cy = iy + ih * 0.59
    top_cx, top_cy = ix + 190, view_cy
    top_r = 82
    view_label_y = view_cy + top_r + 38
    c.setFont("Helvetica-Bold", 9)
    c.drawString(top_cx - 24, view_label_y, "TOP VIEW")
    c.setLineWidth(1.2)
    style_l = style_name.lower()
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
        s = top_r * 1.45
        c.rect(top_cx - s / 2, top_cy - s / 2, s, s, stroke=1, fill=0)
    bore_r = max(14.0, major_d * 5.2)
    c.circle(top_cx, top_cy, bore_r, stroke=1, fill=0)
    c.setDash([2, 2], 0)
    c.line(top_cx - top_r * 1.1, top_cy, top_cx + top_r * 1.1, top_cy)
    c.line(top_cx, top_cy - top_r * 1.1, top_cx, top_cy + top_r * 1.1)
    c.setDash([], 0)

    # Side view (aligned with top view centerline), with chamfered profile.
    sx, sy = ix + 470, view_cy
    side_w = 265
    side_h = 122
    # Light chamfer profile in drawing (not heavy truncation).
    ch = max(5.0, min(10.0, 0.06 * side_h))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(sx + 42, view_label_y, "SIDE VIEW")
    c.setLineWidth(1.2)
    x0 = sx
    x1 = sx + side_w
    y0 = sy - side_h / 2
    y1 = sy + side_h / 2
    pts_side = [
        (x0 + ch, y1),
        (x1 - ch, y1),
        (x1, y1 - ch),
        (x1, y0 + ch),
        (x1 - ch, y0),
        (x0 + ch, y0),
        (x0, y0 + ch),
        (x0, y1 - ch),
    ]
    for i in range(len(pts_side)):
        xa, ya = pts_side[i]
        xb, yb = pts_side[(i + 1) % len(pts_side)]
        c.line(xa, ya, xb, yb)
    c.setDash([2, 2], 0)
    bore_half = max(16.0, major_d * 4.2)
    c.line(sx + side_w * 0.37, sy - bore_half, sx + side_w * 0.37, sy + bore_half)
    c.line(sx + side_w * 0.63, sy - bore_half, sx + side_w * 0.63, sy + bore_half)
    c.setDash([], 0)

    # Dimensions near views (style like main drawing)
    c.setFont("Helvetica", 9)
    corner_d = across / 0.8660254 if style_l.startswith("hex") else across * (2.0**0.5)
    c.drawString(ix + 16, iy + 90, f"Across Flats / Width (S): {across:.2f} mm")
    c.drawString(ix + 16, iy + 74, f"Corner-to-Corner (E): {corner_d:.2f} mm")
    c.drawString(ix + 16, iy + 58, f"Nut Thickness (M): {nut_h:.2f} mm")
    c.drawString(ix + 16, iy + 42, f"Thread Major Dia (D): {major_d:.2f} mm")
    c.drawString(ix + 16, iy + 26, f"Pitch (P): {pitch:.3f} mm")

    # Dimension lines with arrowheads.
    c.setLineWidth(1)
    _dim_h_arrow(top_cx - top_r, top_cx + top_r, top_cy + top_r + 22, top_cy + top_r + 6, top_cy + top_r + 6, f"S={across:.2f}")
    _dim_v_arrow(top_cx + top_r + 20, top_cy - bore_r, top_cy + bore_r, top_cx + top_r + 6, top_cx + top_r + 6, f"D={major_d:.2f}")
    _dim_v_arrow(x1 + 28, y0, y1, x1 + 8, x1 + 8, f"M={nut_h:.2f}")

    # MYSA title block in bottom-right (same family as fastener drawing).
    tb_w = 285
    tb_h = 108
    tb_x = ix + iw - tb_w - 8
    tb_y = iy + 6
    c.rect(tb_x, tb_y, tb_w, tb_h, stroke=1, fill=0)
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
    c.drawString(tb_x + 66, y_part + 8, f"Matching {style_name} Nut"[:42])

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

    _cell(tb_x, top_row_top, "DRAWN BY", os.getenv("DRAWING_AUTHOR", "User")[:20])
    _cell(col1, top_row_top, "APPROVED BY", "Mysa")
    _cell(col2, top_row_top, "DATE", datetime.now().strftime("%Y-%m-%d"))
    _cell(tb_x, bot_row_top, "UNITS", "mm")
    _cell(col1, bot_row_top, "TYPE", style_name)
    _cell(col2, bot_row_top, "SCALE", "NTS")

    c.save()


def _is_yes(answer: str) -> bool:
    return answer.strip().lower() in {"y", "yes"}


def _find_labeled_float(text: str, labels: list[str]) -> float | None:
    label_pat = "|".join(re.escape(l) for l in labels)
    m = re.search(rf"(?:{label_pat})\s*(?:=|:|is|of)?\s*(-?\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    m2 = re.search(rf"(-?\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:{label_pat})", text)
    if m2:
        return float(m2.group(1))
    return None


def _is_standalone_nut_query(text: str) -> bool:
    t = text.lower()
    return ("nut" in t) and ("screw" not in t) and ("bolt" not in t)


def _nut_default_dims(style: str, major_d: float) -> tuple[float, float]:
    style_l = style.strip().lower()
    if style_l.startswith("hex"):
        best_key = min(_HEX_NUT_SIZE_CHART.keys(), key=lambda d: abs(d - major_d))
        return _HEX_NUT_SIZE_CHART[best_key]
    # Square nut practical defaults when no explicit chart value is supplied.
    return (1.50 * major_d, 0.80 * major_d)


def _parse_nut_inputs(text: str, prompt) -> tuple[str, float, float, float]:
    t = text.lower()
    style = "hex" if "hex" in t else ("square" if "square" in t else None)
    major_d = _find_labeled_float(t, ["thread diameter", "major diameter", "diameter", "dia"])
    pitch = _find_labeled_float(t, ["pitch"])
    nut_h = _find_labeled_float(t, ["height", "thickness", "nut height"])

    if style is None:
        s = prompt(_Q_NUT_SHAPE).strip().lower()
        style = "hex" if "hex" in s else ("square" if "square" in s else None)
    if style is None:
        raise ValueError("Nut shape must be hex or square.")
    if major_d is None:
        major_d = float(prompt("Missing nut thread diameter. Enter a value: ").strip())
    if pitch is None:
        # ISO coarse-like approximation when pitch isn't specified.
        pitch = max(0.35, min(3.0, 0.20 * major_d))
    if nut_h is None:
        _, nut_h = _nut_default_dims(style, major_d)
    return style, major_d, pitch, nut_h


def _build_nut_from_params(
    chat: ChatState,
    *,
    style: str,
    major_d: float,
    pitch: float,
    nut_h: float,
    minor_d: float,
    message_prefix: str,
) -> dict[str, Any]:
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

    style_l = style.strip().lower()
    default_across, default_h = _nut_default_dims(style_l, major_d)
    if nut_h <= 0:
        nut_h = default_h
    if style_l.startswith("hex"):
        af = default_across
        poly_d = 2.0 * af / (3.0**0.5)
        body = cq.Workplane("XY").polygon(6, poly_d).extrude(nut_h)
        across = af
        style_name = "Hex"
    else:
        w = default_across
        body = cq.Workplane("XY").rect(w, w).extrude(nut_h)
        across = w
        style_name = "Square"

    body = body.translate((0, 0, -nut_h / 2.0))

    def _is_valid_wp(shape_wp: Any) -> bool:
        try:
            if shape_wp is None:
                return False
            if shape_wp.solids().size() <= 0:
                return False
            return float(shape_wp.val().Volume()) > 1.0e-1
        except Exception:
            return False

    tap_len = nut_h + 2.0
    tap_spec = ShaftSpec(d_minor=minor_d, L=tap_len, tip_len=0.0)
    tap_core = cq.Workplane("XY").circle(minor_d / 2.0).extrude(tap_len)
    try:
        tap = apply_external_thread(
            tap_core,
            tap_spec,
            ThreadParams(
                pitch=pitch,
                length=tap_len,
                start_from_head=0.0,
                included_angle_deg=60.0,
                major_d=max(minor_d + 0.05, major_d - 0.04),
                thread_height=None,
                mode="add",
            ),
        )
        tap = tap.translate((0, 0, -nut_h / 2.0 - 1.0))
        nut = body.cut(tap)
        if not _is_valid_wp(nut):
            raise RuntimeError("Primary threaded cut produced invalid nut.")
    except Exception:
        # Retry with a slightly reduced thread major diameter before giving up.
        try:
            tap_retry = apply_external_thread(
                tap_core,
                tap_spec,
                ThreadParams(
                    pitch=pitch,
                    length=tap_len,
                    start_from_head=0.0,
                    included_angle_deg=60.0,
                    major_d=max(minor_d + 0.03, major_d - 0.12),
                    thread_height=None,
                    mode="add",
                ),
            )
            tap_retry = tap_retry.translate((0, 0, -nut_h / 2.0 - 1.0))
            nut = body.cut(tap_retry)
            if not _is_valid_wp(nut):
                raise RuntimeError("Retry threaded cut produced invalid nut.")
        except Exception:
            bore_r = major_d / 2.0 + 0.08
            bore = cq.Workplane("XY").circle(bore_r).extrude(nut_h + 2.0).translate((0, 0, -nut_h / 2.0 - 1.0))
            nut = body.cut(bore)

    # Keep the latest known-good nut so later style operations can't erase threads.
    base_nut = nut if _is_valid_wp(nut) else body.cut(
        cq.Workplane("XY").circle(max(major_d / 2.0 + 0.08, minor_d / 2.0 + 0.05)).extrude(nut_h + 2.0).translate((0, 0, -nut_h / 2.0 - 1.0))
    )

    # Vertex-only exterior shave:
    # apply a single planar cut per corner (top and bottom) so each corner is
    # "sliced" flat; removed chunk is effectively a pyramid-like corner piece.
    if style_l.startswith("hex") or style_l.startswith("square"):
        try:
            z_box = nut.val().BoundingBox()
            z_top = float(z_box.zmax)
            z_bot = float(z_box.zmin)
            is_hex = style_l.startswith("hex")
            corner_count = 6 if is_hex else 4
            outer_r = float(across) / (3.0**0.5) if is_hex else float(across) / (2.0**0.5)
            corner_phase = 0.0 if is_hex else math.radians(45.0)
            edge_run = max(0.50, min(1.95, 0.15 * float(across)))
            shave_drop = max(0.28, min(0.92, 0.078 * float(across)))

            def _vsub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
                return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

            def _vadd(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
                return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

            def _vscale(a: tuple[float, float, float], s: float) -> tuple[float, float, float]:
                return (a[0] * s, a[1] * s, a[2] * s)

            def _vdot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
                return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

            def _vcross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
                return (
                    a[1] * b[2] - a[2] * b[1],
                    a[2] * b[0] - a[0] * b[2],
                    a[0] * b[1] - a[1] * b[0],
                )

            def _vnorm(a: tuple[float, float, float]) -> float:
                return max(1.0e-12, (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5)

            def _vunit(a: tuple[float, float, float]) -> tuple[float, float, float]:
                n = _vnorm(a)
                return (a[0] / n, a[1] / n, a[2] / n)

            def _plane_cut(
                shp: Any,
                corner_pt: tuple[float, float, float],
                p1: tuple[float, float, float],
                p2: tuple[float, float, float],
                p3: tuple[float, float, float],
            ) -> Any:
                v1 = _vsub(p2, p1)
                v2 = _vsub(p3, p1)
                n = _vcross(v1, v2)
                if _vnorm(n) <= 1.0e-10:
                    return shp
                n = _vunit(n)
                u = _vunit(v1)

                center = _vscale(_vadd(_vadd(p1, p2), p3), 1.0 / 3.0)
                # Orient plane normal toward corner side so the cut removes the corner.
                if _vdot(n, _vsub(corner_pt, center)) < 0.0:
                    n = _vscale(n, -1.0)
                # Ensure xDir is not parallel to normal.
                if _vnorm(_vcross(u, n)) <= 1.0e-9:
                    u = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)

                plane = cq.Plane(origin=center, xDir=u, normal=n)
                tool = (
                    cq.Workplane(plane)
                    .rect(4.0 * float(across), 4.0 * float(across))
                    .extrude(max(3.0 * float(across), 3.0 * float(nut_h)))
                )
                return shp.cut(tool)

            cand = nut
            step = 360.0 / float(corner_count)
            for i in range(corner_count):
                a = corner_phase + math.radians(step * i)
                c_xy = (outer_r * math.cos(a), outer_r * math.sin(a))
                prev_xy = (outer_r * math.cos(a - math.radians(step)), outer_r * math.sin(a - math.radians(step)))
                next_xy = (outer_r * math.cos(a + math.radians(step)), outer_r * math.sin(a + math.radians(step)))

                d1 = _vunit((prev_xy[0] - c_xy[0], prev_xy[1] - c_xy[1], 0.0))
                d2 = _vunit((next_xy[0] - c_xy[0], next_xy[1] - c_xy[1], 0.0))

                # Top corner plane points.
                c_top = (c_xy[0], c_xy[1], z_top)
                p1_top = (c_xy[0] + edge_run * d1[0], c_xy[1] + edge_run * d1[1], z_top)
                p2_top = (c_xy[0] + edge_run * d2[0], c_xy[1] + edge_run * d2[1], z_top)
                p3_top = (c_xy[0], c_xy[1], z_top - shave_drop)

                # Bottom corner plane points.
                c_bot = (c_xy[0], c_xy[1], z_bot)
                p1_bot = (c_xy[0] + edge_run * d1[0], c_xy[1] + edge_run * d1[1], z_bot)
                p2_bot = (c_xy[0] + edge_run * d2[0], c_xy[1] + edge_run * d2[1], z_bot)
                p3_bot = (c_xy[0], c_xy[1], z_bot + shave_drop)

                cand = _plane_cut(cand, c_top, p1_top, p2_top, p3_top)
                cand = _plane_cut(cand, c_bot, p1_bot, p2_bot, p3_bot)

            if _is_valid_wp(cand):
                nut = cand
        except Exception:
            pass

    if not _is_valid_wp(nut):
        nut = base_nut

    # Guardrail: never export an empty/invalid nut shape.
    if not _is_valid_wp(nut):
        try:
            if style_l.startswith("hex"):
                poly_d_fb = 2.0 * across / (3.0**0.5)
                fallback_body = cq.Workplane("XY").polygon(6, poly_d_fb).extrude(nut_h)
            else:
                fallback_body = cq.Workplane("XY").rect(across, across).extrude(nut_h)
            fallback_body = fallback_body.translate((0, 0, -nut_h / 2.0))
            fallback_bore = (
                cq.Workplane("XY")
                .circle(max(major_d / 2.0 + 0.08, minor_d / 2.0 + 0.05))
                .extrude(nut_h + 2.0)
                .translate((0, 0, -nut_h / 2.0 - 1.0))
            )
            nut = fallback_body.cut(fallback_bore)
        except Exception:
            pass

    if not _is_valid_wp(nut):
        chat.pending_question = None
        return {
            "status": "error",
            "error": "Failed to generate a valid nut solid.",
            "message": _bot(
                chat,
                "I couldn't build a valid nut geometry from that request. Please try again with slightly larger nut dimensions.",
                kind="error",
            ),
        }

    stem = _unique_output_stem(f"nut_{style_name.lower()}_d{major_d:.2f}_p{pitch:.2f}")
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
        _solidify_preview_svg(preview_path)
        preview_url = f"/downloads/{preview_path.name}?v={int(datetime.now().timestamp() * 1000)}"
    except Exception:
        preview_url = ""

    drawing_url = ""
    try:
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
    prefix = (message_prefix.strip() + " ") if message_prefix.strip() else ""
    msg = _bot(
        chat,
        f"{prefix}{style_name} nut generated.",
        kind="result",
        extra=chat.latest_files,
    )
    return {"status": "ok", "message": msg}


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
    _, nut_h = _nut_default_dims(nut_style, major_d)
    return _build_nut_from_params(
        chat,
        style=nut_style,
        major_d=major_d,
        pitch=pitch,
        nut_h=nut_h,
        minor_d=base.shaft.d_minor,
        message_prefix="Matching",
    )


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
    drive_tag = spec.drive.type if spec.drive is not None else "nodrive"
    threaded = any(isinstance(r, ThreadRegionSpec) for r in spec.regions)
    th_tag = "th" if threaded else "sm"
    stem = _unique_output_stem(
        f"{spec.fastener_type}_{spec.head.type}_{drive_tag}_d{spec.shaft.d_minor:.2f}_l{spec.shaft.L:.2f}_{th_tag}"
    )
    try:
        screw = make_screw_from_spec(spec, include_thread_markers=False)
    except (ValueError, Exception) as build_err:
        chat.pending_question = None
        return {
            "status": "error",
            "error": str(build_err),
            "message": _bot(
                chat,
                f"Could not build geometry: {build_err}. Please adjust dimensions (e.g. shorten thread length or increase overall length) and try again.",
                kind="error",
            ),
        }
    step_path = export_step(screw, _DOWNLOAD_DIR / f"{stem}.step")
    stl_path = export_stl(screw, _DOWNLOAD_DIR / f"{stem}.stl")
    preview_path = _DOWNLOAD_DIR / f"{stem}.svg"
    drawing_pdf_path = _DOWNLOAD_DIR / f"{stem}_drawing.pdf"
    drawing_svg_path = _DOWNLOAD_DIR / f"{stem}_drawing.svg"
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
            exporters.export(
                screw,
                str(preview_path),
                exportType="SVG",
                opt={"showAxes": False, "showHidden": False},
            )
        _solidify_preview_svg(preview_path)
        preview_url = f"/downloads/{preview_path.name}?v={int(datetime.now().timestamp() * 1000)}"
    except Exception:
        preview_url = ""
    drawing_export_path: Path | None = None
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
            drawing_pdf_path,
            screw_name=chat.title,
            author_name=os.getenv("DRAWING_AUTHOR", "User"),
            iso_svg_path=iso_preview_path,
        )
        drawing_export_path = drawing_pdf_path
        drawing_url = f"/downloads/{drawing_pdf_path.name}"
    except Exception:
        # Fallback keeps "Download Drawing" usable even if PDF deps are missing.
        try:
            _write_engineering_drawing_svg(spec, drawing_svg_path)
            drawing_export_path = drawing_svg_path
            drawing_url = f"/downloads/{drawing_svg_path.name}"
        except Exception:
            drawing_url = ""
    try:
        with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(step_path, arcname=step_path.name)
            bundle.write(stl_path, arcname=stl_path.name)
            if drawing_export_path is not None:
                bundle.write(drawing_export_path, arcname=drawing_export_path.name)
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
        f"{chat.title} generated.",
        kind="result",
        extra=chat.latest_files,
    )
    return {"status": "ok", "message": msg}


def _attempt_build(
    chat: ChatState,
    *,
    use_prompt: bool = True,
    apply_realism_checks: bool = True,
) -> dict[str, Any]:
    def _prompt(q: str) -> str:
        if q in chat.answers:
            return chat.answers[q]
        raise _NeedInput(q)

    if _is_standalone_nut_query(chat.query):
        try:
            style, major_d, pitch, nut_h = _parse_nut_inputs(chat.query, _prompt)
            # Approximate minor diameter for standalone nut threading from pitch.
            minor_d = max(0.2 * major_d, major_d - 1.2 * pitch)
            chat.latest_spec = None
            chat.pending_question = None
            chat.title = f"{style.title()} Nut"
            return _build_nut_from_params(
                chat,
                style=style,
                major_d=major_d,
                pitch=pitch,
                nut_h=nut_h,
                minor_d=minor_d,
                message_prefix="",
            )
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
                "message": _bot(chat, f"Could not generate nut: {exc}", kind="error"),
            }

    try:
        spec = screw_spec_from_query(
            chat.query,
            prompt=(_prompt if use_prompt else None),
            apply_realism_checks=apply_realism_checks,
        )
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


@app.get("/brand-bg")
def brand_bg() -> FileResponse:
    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if not _BRAND_BG.exists():
        raise HTTPException(status_code=404, detail="Brand background not found.")
    return FileResponse(_BRAND_BG, headers=no_cache_headers)


@app.get("/downloads/{filename:path}")
def download_generated_file(filename: str) -> FileResponse:
    target = (_DOWNLOAD_DIR / filename).resolve()
    try:
        target.relative_to(_DOWNLOAD_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid download path.") from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if target.suffix.lower() == ".svg":
        _solidify_preview_svg(target)
    return FileResponse(target, headers=no_cache_headers)


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

    if chat.pending_flow == "image_estimate_confirm":
        if content:
            _user(chat, content)
        if _is_yes(content):
            if not chat.image_estimate_query:
                chat.pending_flow = None
                chat.pending_question = None
                _bot(chat, "I lost the image estimate context. Please upload the image again.", kind="error")
                return {
                    "chat_id": chat.id,
                    "status": "error",
                    "messages": chat.messages,
                    "pending_question": chat.pending_question,
                }
            chat.pending_flow = None
            chat.pending_question = None
            chat.query = chat.image_estimate_query
            chat.answers = {}
            result = _attempt_build(chat, use_prompt=False, apply_realism_checks=False)
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
        chat.pending_flow = "image_estimate_edit"
        chat.pending_question = _Q_IMAGE_ESTIMATE_EDIT
        _bot(chat, _Q_IMAGE_ESTIMATE_EDIT, kind="question")
        return {
            "chat_id": chat.id,
            "status": "needs_input",
            "question": chat.pending_question,
            "messages": chat.messages,
            "pending_question": chat.pending_question,
        }

    if chat.pending_flow == "image_estimate_edit":
        if not content:
            raise HTTPException(status_code=400, detail="Please provide corrections to continue.")
        _user(chat, content)
        if not chat.image_estimate_query:
            chat.pending_flow = None
            chat.pending_question = None
            _bot(chat, "I lost the image estimate context. Please upload the image again.", kind="error")
            return {
                "chat_id": chat.id,
                "status": "error",
                "messages": chat.messages,
                "pending_question": chat.pending_question,
            }
        chat.pending_flow = None
        chat.pending_question = None
        chat.query = f"{chat.image_estimate_query} {content}"
        chat.answers = {}
        result = _attempt_build(chat, use_prompt=False, apply_realism_checks=False)
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


@app.post("/api/chats/{chat_id}/image")
async def post_image(chat_id: int, file: UploadFile = File(...), content: str = Form("")) -> dict[str, Any]:
    chat = _chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    ctype = (file.content_type or "").lower()
    if not ctype.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported.")

    data = await file.read()
    image_path, image_url = _save_uploaded_image(file, data)
    caption = content.strip() or "Uploaded reference image"
    _user(chat, caption, kind="image", extra={"image_url": image_url})

    est_query, summary = _estimate_query_from_image(image_path)
    chat.image_estimate_query = est_query
    chat.pending_flow = "image_estimate_confirm"
    chat.pending_question = _Q_IMAGE_ESTIMATE_CONFIRM
    _bot(chat, f"{summary}\n\n{_Q_IMAGE_ESTIMATE_CONFIRM}", kind="question")

    return {
        "chat_id": chat.id,
        "status": "needs_input",
        "question": chat.pending_question,
        "messages": chat.messages,
        "pending_question": chat.pending_question,
    }

