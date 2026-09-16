from __future__ import annotations

import json
from pathlib import Path

import pytest

from gway_web import commands
from gway_web.log_query import list_log_runs, log_source, read_log_events


def _write_run(root: Path, run_id: str, events: list[dict[str, object]]) -> None:
    run = root / run_id
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def test_semantic_log_source_precedes_legacy_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    semantic = tmp_path / "semantic"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("GWAY_LOGS_SOURCE", str(semantic))
    monkeypatch.setenv("GWAY_LOG_DIR", str(legacy))

    assert log_source() == semantic


def test_legacy_log_source_remains_compatible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    legacy = tmp_path / "legacy"
    monkeypatch.delenv("GWAY_LOGS_SOURCE", raising=False)
    monkeypatch.setenv("GWAY_LOG_DIR", str(legacy))

    assert log_source() == legacy


def test_explicit_log_source_precedes_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("GWAY_LOGS_SOURCE", str(tmp_path / "semantic"))

    assert log_source(explicit) == explicit


def test_log_query_is_bounded_and_cursor_based(tmp_path: Path):
    root = tmp_path / "runs"
    events = [{"sequence": index, "message": f"event-{index}"} for index in range(1, 6)]
    _write_run(root, "run-1", events)

    first = read_log_events("run-1", root, limit=2)
    assert first["events"] == events[:2]
    assert first["next_cursor"] == 2
    assert first["has_more"] is True

    second = read_log_events("run-1", root, after=2, limit=2)
    assert second["events"] == events[2:4]
    assert second["next_cursor"] == 4
    assert second["has_more"] is True

    final = read_log_events("run-1", root, after=4, limit=2)
    assert final["events"] == events[4:]
    assert final["next_cursor"] == 5
    assert final["has_more"] is False


def test_log_query_rejects_unbounded_limits(tmp_path: Path):
    with pytest.raises(ValueError, match="limit"):
        list_log_runs(tmp_path, limit=0)
    with pytest.raises(ValueError, match="limit"):
        list_log_runs(tmp_path, limit=1001)


def test_logs_command_lists_runs_instead_of_starting_service(tmp_path: Path):
    root = tmp_path / "runs"
    _write_run(root, "run-1", [{"message": "hello"}])

    result = commands.logs(source=str(root))

    assert [item["run_id"] for item in result["runs"]] == ["run-1"]


def test_logs_command_reads_one_run_incrementally(tmp_path: Path):
    root = tmp_path / "runs"
    events = [{"message": "first"}, {"message": "second"}]
    _write_run(root, "run-1", events)

    first = commands.logs("run-1", source=str(root), limit=1)
    second = commands.logs("run-1", source=str(root), after=int(first["next_cursor"]), limit=1)

    assert first["events"] == events[:1]
    assert second["events"] == events[1:]


def test_logs_command_requires_run_for_after(tmp_path: Path):
    with pytest.raises(ValueError, match="requires a run id"):
        commands.logs(source=str(tmp_path), after=1)
