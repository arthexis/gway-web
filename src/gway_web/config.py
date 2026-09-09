"""Declarative site configuration."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .site import Site

ENV_CONFIG = "GWAY_WEB_CONFIG"
DEFAULT_CONFIG = Path("~/.config/gway/web.toml").expanduser()


def config_path() -> Path:
    """Return the configured site manifest path."""
    return Path(os.environ.get(ENV_CONFIG, DEFAULT_CONFIG)).expanduser()


def read_sites(path: str | Path | None = None) -> list[Site]:
    """Read site definitions from TOML; a missing default file means no sites."""
    target = Path(path).expanduser() if path is not None else config_path()
    if not target.exists():
        if path is None:
            return []
        raise FileNotFoundError(target)
    with target.open("rb") as stream:
        data = tomllib.load(stream)
    table = data.get("sites", {})
    if not isinstance(table, dict):
        raise ValueError("sites must be a TOML table")
    result: list[Site] = []
    for name, values in table.items():
        if not isinstance(values, dict):
            raise ValueError(f"site {name!r} must be a TOML table")
        result.append(Site(name=name, **values))
    return result
