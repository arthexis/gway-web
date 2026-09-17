"""Read-only queries over the GWAY Web log store.

The public command and future MCP adapter use this module; service lifecycle stays
in GWAY's generic service manager and ``gway_web.log_service``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .logs import default_log_root, list_runs, read_run

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


def list_log_runs(
    source: str | Path | None = None,
    *,
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, object]]:
    """Return the most recently modified runs, bounded for remote-safe reuse."""
    return list_runs(log_source(source))[: _bounded_limit(limit)]


def read_log_events(
    run_id: str,
    source: str | Path | None = None,
    *,
    after: int | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, object]:
    """Read a bounded page of append-only JSON log events.

    The cursor is the number of event lines already consumed. Passing the
    returned ``next_cursor`` as ``after`` therefore yields only newly appended
    events without depending on an event-specific sequence field.
    """
    selected_limit = _bounded_limit(limit)
    cursor = 0 if after is None else after
    if cursor < 0:
        raise ValueError("after must be zero or greater")

    raw = read_run(run_id, log_source(source))
    lines = [line for line in raw.splitlines() if line.strip()]
    page = lines[cursor : cursor + selected_limit]
    events: list[dict[str, object]] = []
    for offset, line in enumerate(page, start=cursor + 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON event at line {offset}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"log event at line {offset} is not an object")
        events.append(event)

    next_cursor = cursor + len(events)
    return {
        "run_id": run_id,
        "events": events,
        "next_cursor": next_cursor,
        "has_more": next_cursor < len(lines),
    }
