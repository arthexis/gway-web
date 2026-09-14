from __future__ import annotations

from pathlib import Path

import pytest

from gway_web.logs import default_log_root, list_runs, read_run


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
