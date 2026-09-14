from __future__ import annotations

import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from gway_web import commands
from gway_web.logs import LogRequestHandler, default_log_root, list_runs, read_run, serve_logs


def test_default_log_root_matches_gway_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    configured = tmp_path / "runs"
    monkeypatch.setenv("GWAY_LOG_DIR", str(configured))

    assert default_log_root() == configured


def test_default_log_root_uses_xdg_state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GWAY_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    assert default_log_root() == tmp_path / "gway" / "runs"


def test_runs_are_discovered_from_default_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "runs"
    run = root / "20260914T150000Z-abc123"
    run.mkdir(parents=True)
    events = b'{"kind":"command.start"}\n{"kind":"command.end"}\n'
    (run / "events.jsonl").write_bytes(events)
    monkeypatch.setenv("GWAY_LOG_DIR", str(root))

    assert list_runs()[0]["run_id"] == run.name
    assert read_run(run.name) == events


def test_source_override_does_not_require_gway_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("GWAY_LOG_DIR", raising=False)
    run = tmp_path / "custom" / "run-1"
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text('{"kind":"test"}\n', encoding="utf-8")

    assert list_runs(tmp_path / "custom")[0]["run_id"] == "run-1"


def test_read_run_rejects_traversal(tmp_path: Path):
    with pytest.raises(ValueError, match="invalid run id"):
        read_run("../secrets", tmp_path)


def test_read_run_rejects_symlink_escape(tmp_path: Path):
    root = tmp_path / "runs"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "events.jsonl").write_text("secret\n", encoding="utf-8")
    root.mkdir()
    try:
        (root / "escaped").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="invalid run path"):
        read_run("escaped", root)


def test_plain_log_server_rejects_non_loopback_binding(tmp_path: Path):
    with pytest.raises(ValueError, match="loopback"):
        serve_logs(source=tmp_path, host="0.0.0.0", port=0)


def _status(url: str, token: str | None = None) -> tuple[int, bytes]:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def test_log_routes_require_valid_read_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "runs"
    run = source / "run-1"
    run.mkdir(parents=True)
    events = b'{"kind":"test"}\n'
    (run / "events.jsonl").write_bytes(events)
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(tmp_path / "tokens.json"))

    reader = str(commands.token(name="reader", scope="logs:read", ttl=3600)["token"])
    writer = str(commands.token(name="writer", scope="logs:ingest", ttl=3600)["token"])

    handler = partial(LogRequestHandler, source=source.resolve())
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for route in ("/api/logs/runs", "/api/logs/run-1/events"):
            assert _status(base + route)[0] == 401
            assert _status(base + route, "invalid")[0] == 401
            assert _status(base + route, writer)[0] == 401
            status, body = _status(base + route, reader)
            assert status == 200
            if route.endswith("/runs"):
                assert json.loads(body)["runs"][0]["run_id"] == "run-1"
            else:
                assert body == events
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
