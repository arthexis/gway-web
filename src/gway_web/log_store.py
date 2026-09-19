"""Filesystem helpers for the local GWAY log store."""

from __future__ import annotations

import os
from pathlib import Path

_LOG_DIR_ENV = "GWAY_LOG_DIR"


def default_log_root() -> Path:
    """Return the canonical local GWAY run root."""
    configured = os.environ.get(_LOG_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home).expanduser() / "gway" / "runs"
    return Path.home() / ".local" / "state" / "gway" / "runs"


def log_root(source: str | Path | None = None) -> Path:
    """Resolve an explicit source or the canonical local log root."""
    return Path(source).expanduser() if source is not None else default_log_root()


def _safe_run_id(value: str) -> bool:
    """Return whether a run identifier is one safe path component."""
    if not value or value in {".", ".."}:
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and path.name == value
        and "/" not in value
        and "\\" not in value
    )


def event_path(run_id: str, source: str | Path | None = None) -> Path:
    """Return a contained event path for one validated run identifier."""
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


__all__ = ["default_log_root", "event_path", "log_root"]
