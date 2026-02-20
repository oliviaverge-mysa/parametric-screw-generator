"""Local chat-style web app for interactive screw generation."""

from __future__ import annotations

import itertools
import re
import time
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
    try:
        exporters.export(screw, str(preview_path), exportType="SVG")
        preview_url = f"/downloads/{preview_path.name}"
    except Exception:
        preview_url = ""

    step_url = f"/downloads/{step_path.name}"
    stl_url = f"/downloads/{stl_path.name}"
    chat.latest_files = {"step_url": step_url, "stl_url": stl_url, "preview_url": preview_url}
    msg = _bot(
        chat,
        "Screw generated. Use the buttons to download STEP/STL or inspect STL preview.",
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

