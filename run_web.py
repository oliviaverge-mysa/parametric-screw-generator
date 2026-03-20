"""Run local ScrewGen chat web app."""

from __future__ import annotations

import os
import sys
import socket
from pathlib import Path

import uvicorn

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.is_file():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k, _v = _k.strip(), _v.strip()
            if _k and _k not in os.environ:
                os.environ[_k] = _v


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1").strip()
    port = int(os.getenv("PORT", "0").strip() or "0")
    if port == 0:
        for candidate in (8000, 8001, 8002, 8003):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex((host, candidate)) != 0:
                    port = candidate
                    break
        else:
            port = 8000
    print(f"Starting web UI on http://{host}:{port}")
    uvicorn.run("screwgen.webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

