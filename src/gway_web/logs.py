from __future__ import annotations

import json
import os
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .tokens import verify_token

_LOG_DIR_ENV = "GWAY_LOG_DIR"


def default_log_root() -> Path:
    """Return the same canonical run root used by GWAY logging."""
    configured = os.environ.get(_LOG_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home).expanduser() / "gway" / "runs"
    return Path.home() / ".local" / "state" / "gway" / "runs"


def log_root(source: str | Path | None = None) -> Path:
    return Path(source).expanduser() if source is not None else default_log_root()


def _safe_run_id(value: str) -> bool:
    if not value or value in {".", ".."}:
        return False
    path = Path(value)
    return not path.is_absolute() and path.name == value and "/" not in value and "\\" not in value


def list_runs(source: str | Path | None = None) -> list[dict[str, object]]:
    root = log_root(source)
    if not root.exists():
        return []
    runs: list[dict[str, object]] = []
    for directory in root.iterdir():
        events = directory / "events.jsonl"
        if not directory.is_dir() or not events.is_file():
            continue
        stat = events.stat()
        runs.append(
            {
                "run_id": directory.name,
                "bytes": stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    return sorted(runs, key=lambda item: float(item["modified"]), reverse=True)


def read_run(run_id: str, source: str | Path | None = None) -> bytes:
    if not _safe_run_id(run_id):
        raise ValueError("invalid run id")
    path = log_root(source) / run_id / "events.jsonl"
    return path.read_bytes()


class LogRequestHandler(BaseHTTPRequestHandler):
    server_version = "GwayWebLogs/0.1"

    def __init__(self, *args, source: Path, **kwargs):
        self.log_source = source
        super().__init__(*args, **kwargs)

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = (json.dumps(payload, default=str) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return verify_token(header[7:].strip(), scope="logs:read")

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/health":
            self._json(HTTPStatus.OK, {"ok": True, "source": str(self.log_source)})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "valid logs:read bearer token required"})
            return
        if path == "/api/logs/runs":
            self._json(HTTPStatus.OK, {"runs": list_runs(self.log_source)})
            return
        prefix = "/api/logs/"
        suffix = "/events"
        if path.startswith(prefix) and path.endswith(suffix):
            run_id = unquote(path[len(prefix) : -len(suffix)]).strip("/")
            try:
                body = read_run(run_id, self.log_source)
            except (ValueError, OSError):
                self._json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: object) -> None:
        return


def serve_logs(
    *,
    source: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8040,
) -> None:
    """Serve the local GWAY log store until interrupted."""
    root = log_root(source).resolve()
    handler = partial(LogRequestHandler, source=root)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
