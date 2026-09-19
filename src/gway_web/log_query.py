"""Read-only queries over the local GWAY log store.

The public command and MCP adapter use this module without depending on a
dedicated Web log service.
"""

from __future__ import annotations

import heapq
import json
from pathlib import Path

from .log_store import default_log_root, event_path

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000


def log_source(source: str | Path | None = None) -> Path:
    """Return an explicit log source or the legacy log-store default.

    Semantic configuration such as ``logs.source`` is resolved by GWAY before
    calling this module. The underlying log store retains its existing default
    behavior for direct/internal callers and legacy producers.
    """
    if source is not None:
        return Path(source).expanduser()
    return default_log_root()


def _bounded_limit(limit: int) -> int:
    if limit < 1 or limit > _MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")
    return limit


def _run_metadata(run_id: str, source: str | Path | None = None) -> dict[str, object]:
    """Return metadata for one exact run without scanning the run store."""
    path = event_path(run_id, log_source(source))
    stat = path.stat()
    return {
        "run_id": run_id,
        "bytes": stat.st_size,
        "modified": stat.st_mtime,
    }


def get_log_run(run_id: str, source: str | Path | None = None) -> dict[str, object]:
    """Return metadata for one exact run or raise ``KeyError`` when absent."""
    try:
        return _run_metadata(run_id, source)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise KeyError(f"unknown run: {run_id}") from exc


def list_log_runs(
    source: str | Path | None = None,
    *,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, object]]:
    """Return the newest run metadata while retaining only the bounded result set."""
    selected_limit = _bounded_limit(limit)
    root = log_source(source)
    if not root.exists():
        return []

    newest: list[tuple[float, str, dict[str, object]]] = []
    for directory in root.iterdir():
        events = directory / "events.jsonl"
        if not directory.is_dir() or not events.is_file():
            continue
        stat = events.stat()
        item: dict[str, object] = {
            "run_id": directory.name,
            "bytes": stat.st_size,
            "modified": stat.st_mtime,
        }
        entry = (stat.st_mtime, directory.name, item)
        if len(newest) < selected_limit:
            heapq.heappush(newest, entry)
        elif entry[:2] > newest[0][:2]:
            heapq.heapreplace(newest, entry)

    newest.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [entry[2] for entry in newest]


def read_log_events(
    run_id: str,
    source: str | Path | None = None,
    *,
    after: int | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, object]:
    """Read a bounded page of append-only JSON log events.

    The cursor is the number of non-empty event lines already consumed. Passing
    the returned ``next_cursor`` as ``after`` therefore yields only newly
    appended events without depending on an event-specific sequence field.
    """
    selected_limit = _bounded_limit(limit)
    cursor = 0 if after is None else after
    if cursor < 0:
        raise ValueError("after must be zero or greater")

    path = event_path(run_id, log_source(source))
    page: list[tuple[int, str]] = []
    consumed = 0
    with path.open("r", encoding="utf-8") as stream:
        for physical_line, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if consumed < cursor:
                consumed += 1
                continue
            if len(page) >= selected_limit + 1:
                break
            page.append((physical_line, line))
            consumed += 1

    has_more = len(page) > selected_limit
    selected_page = page[:selected_limit]
    events: list[dict[str, object]] = []
    for physical_line, line in selected_page:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON event at line {physical_line}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"log event at line {physical_line} is not an object")
        events.append(event)

    next_cursor = cursor + len(events)
    return {
        "run_id": run_id,
        "events": events,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


__all__ = ["get_log_run", "list_log_runs", "log_source", "read_log_events"]
