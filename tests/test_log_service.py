from __future__ import annotations

from pathlib import Path

import pytest

from gway_web import log_service


def test_log_service_requires_source() -> None:
    with pytest.raises(SystemExit):
        log_service.main([])


def test_log_service_forwards_resolved_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: dict[str, object] = {}

    def fake_serve_logs(*, source, host="127.0.0.1", port=8040) -> None:
        observed["source"] = source
        observed["host"] = host
        observed["port"] = port

    monkeypatch.setattr(log_service, "serve_logs", fake_serve_logs)

    source = tmp_path / "runs"
    log_service.main(["--source", str(source)])

    assert observed == {
        "source": str(source),
        "host": "127.0.0.1",
        "port": 8040,
    }
