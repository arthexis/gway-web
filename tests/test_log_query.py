from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from gway_web import commands
from gway_web.log_query import get_log_run, list_log_runs, log_source, read_log_events


def _write_run(root: Path, run_id: str, events: list[dict[str, object]]) -> None:
    run = root / run_id
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def test_log_source_uses_explicit_source(tmp_path: Path):
    explicit = tmp_path / "explicit"

    assert log_source(explicit) == explicit


def test_log_source_keeps_legacy_store_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("GWAY_LOG_DIR", str(legacy))

    assert log_source() == legacy


def test_log_commands_declare_semantic_source_sigil():
    for command in (commands.list_runs, commands.get_run, commands.get_events, commands.logs):
        source = inspect.signature(command).parameters["source"]
        assert source.default == "[logs.source]"


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


def test_event_paging_does_not_materialize_complete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "runs"
    events = [{"sequence": index} for index in range(200)]
    _write_run(root, "run-1", events)

    def fail_read_bytes(self: Path) -> bytes:
        raise AssertionError("event paging must not use Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    page = read_log_events("run-1", root, after=50, limit=3)

    assert page["events"] == events[50:53]
    assert page["next_cursor"] == 53
    assert page["has_more"] is True


def test_log_query_rejects_unbounded_limits(tmp_path: Path):
    with pytest.raises(ValueError, match="limit"):
        list_log_runs(tmp_path, limit=0)
    with pytest.raises(ValueError, match="limit"):
        list_log_runs(tmp_path, limit=1001)


def test_list_runs_command_returns_recent_runs(tmp_path: Path):
    root = tmp_path / "runs"
    _write_run(root, "run-1", [{"message": "hello"}])

    result = commands.list_runs(source=str(root))

    assert [item["run_id"] for item in result["runs"]] == ["run-1"]


def test_get_log_run_resolves_exact_run_without_recent_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "runs"
    _write_run(root, "run-1", [{"message": "hello"}])

    def fail_iterdir(self: Path):
        raise AssertionError("exact run lookup must not enumerate the run store")

    monkeypatch.setattr(Path, "iterdir", fail_iterdir)

    result = get_log_run("run-1", root)

    assert result["run_id"] == "run-1"


def test_get_run_command_returns_one_run_metadata(tmp_path: Path):
    root = tmp_path / "runs"
    _write_run(root, "run-1", [{"message": "hello"}])

    result = commands.get_run("run-1", source=str(root))

    assert result["run_id"] == "run-1"
    assert int(result["bytes"]) > 0
    assert float(result["modified"]) > 0


def test_get_run_command_rejects_unknown_run(tmp_path: Path):
    with pytest.raises(KeyError, match="unknown run"):
        commands.get_run("missing", source=str(tmp_path))


def test_get_events_command_reads_one_run_incrementally(tmp_path: Path):
    root = tmp_path / "runs"
    events = [{"message": "first"}, {"message": "second"}]
    _write_run(root, "run-1", events)

    first = commands.get_events("run-1", source=str(root), limit=1)
    second = commands.get_events(
        "run-1",
        source=str(root),
        after=int(first["next_cursor"]),
        limit=1,
    )

    assert first["events"] == events[:1]
    assert second["events"] == events[1:]


def test_logs_command_remains_compatible(tmp_path: Path):
    root = tmp_path / "runs"
    events = [{"message": "first"}, {"message": "second"}]
    _write_run(root, "run-1", events)

    listed = commands.logs(source=str(root))
    page = commands.logs("run-1", source=str(root), limit=1)

    assert [item["run_id"] for item in listed["runs"]] == ["run-1"]
    assert page["events"] == events[:1]


def test_logs_command_requires_run_for_after(tmp_path: Path):
    with pytest.raises(ValueError, match="requires a run id"):
        commands.logs(source=str(tmp_path), after=1)
