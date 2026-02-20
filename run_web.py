"""Run local ScrewGen chat web app."""

from __future__ import annotations

import sys
import socket
from pathlib import Path

import uvicorn

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    for candidate in (8000, 8001, 8002, 8003):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex((host, candidate)) != 0:
                port = candidate
                break
    print(f"Starting web UI on http://{host}:{port}")
    uvicorn.run("screwgen.webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

