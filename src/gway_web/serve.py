"""Small Python-side serving facility for development and simple static sites."""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def serve(
    root: str | Path = ".",
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Serve *root* over HTTP until interrupted."""
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"web root is not a directory: {directory}")
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
