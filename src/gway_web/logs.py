from __future__ import annotations

import ipaddress
import json
import os
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .tokens import verify_token

_LOG_DIR_ENV = "GWAY_LOG_DIR"
_STREAM_CHUNK_SIZE = 64 * 1024


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
    """Resolve the configured or explicit log-store root."""
    return Path(source).expanduser() if source is not None else default_log_root()


def _safe_run_id(value: str) -> bool:
    """Return whether a run identifier is a single safe path component."""
    if not value or value in {".", ".."}:
        return False
    path = Path(value)
    return not path.is_absolute() and path.name == value and "/" not in value and "\\" not in value


def _event_path(run_id: str, source: str | Path | None = None) -> Path:
    """Return a contained, resolved event path for a validated run identifier."""
    if not _safe_run_id(run_id):
        raise ValueError("invalid run id")
    root = log_root(source).resolve()
    path = (root / run_id / "events.jsonl").resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("invalid run path") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def list_runs(source: str | Path | None = None) -> list[dict[str, object]]:
    """List runs that contain an event stream under the selected log root."""
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
    """Read a contained run event file for local callers."""
    return _event_path(run_id, source).read_bytes()


class LogRequestHandler(BaseHTTPRequestHandler):
    """Serve health and authenticated log-read endpoints."""

    server_version = "GwayWebLogs/0.1"

    def __init__(self, *args, source: Path, **kwargs):
        self.log_source = source
        super().__init__(*args, **kwargs)

    def _json(self, status: HTTPStatus, payload: object) -> None:
        """Send one JSON response."""
        body = (json.dumps(payload, default=str) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        """Require a bearer credential carrying the log-read scope."""
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return verify_token(header[7:].strip(), scope="logs:read")

    def _stream_events(self, run_id: str) -> None:
        """Stream one run without allocating the complete event file."""
        path = _event_path(run_id, self.log_source)
        size = path.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with path.open("rb") as stream:
            while chunk := stream.read(_STREAM_CHUNK_SIZE):
                self.wfile.write(chunk)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        """Handle health, run-list, and event-stream requests."""
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
                self._stream_events(run_id)
            except (ValueError, OSError):
                self._json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: object) -> None:
        """Suppress the stdlib access log; GWAY owns execution logging."""
        return


def _loopback_host(host: str) -> bool:
    """Return whether a bind host is restricted to the local machine."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def serve_logs(
    *,
    source: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8040,
) -> None:
    """Serve the local GWAY log store on loopback until interrupted."""
    if not _loopback_host(host):
        raise ValueError("plain HTTP log service must bind to a loopback address")
    root = log_root(source).resolve()
    handler = partial(LogRequestHandler, source=root)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
