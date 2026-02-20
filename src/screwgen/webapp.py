"""Local chat-style web app for interactive screw generation."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .search_parser import screw_spec_from_query


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
    message_count: int


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
    chat = ChatState(id=cid, title=title or f"Chat {cid}")
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
    stem = f"chat{chat.id}_{stamp}"
    screw = make_screw_from_spec(spec, include_thread_markers=False)
    step_path = export_step(screw, _DOWNLOAD_DIR / f"{stem}.step")
    stl_path = export_stl(screw, _DOWNLOAD_DIR / f"{stem}.stl")

    step_url = f"/downloads/{step_path.name}"
    stl_url = f"/downloads/{stl_path.name}"
    chat.latest_files = {"step_url": step_url, "stl_url": stl_url}
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
        ChatSummary(id=c.id, title=c.title, message_count=len(c.messages))
        for c in sorted(_chats.values(), key=lambda x: x.id)
    ]


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
    chat.messages[msg_idx]["content"] = body.content
    return {"ok": True, "message": chat.messages[msg_idx]}


@app.post("/api/chats/{chat_id}/messages")
def post_message(chat_id: int, body: MessageIn) -> dict[str, Any]:
    chat = _chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found.")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    _user(chat, content)

    if chat.pending_question is None:
        chat.query = content
        chat.answers = {}
    else:
        chat.answers[chat.pending_question] = content

    result = _attempt_build(chat)
    return {"chat_id": chat.id, **result, "messages": chat.messages, "pending_question": chat.pending_question}

