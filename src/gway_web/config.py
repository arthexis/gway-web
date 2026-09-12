"""Declarative site configuration."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

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
        raise TypeError("sites must be a TOML table")
    result: list[Site] = []
    for name, values in table.items():
        if not isinstance(values, dict):
            raise TypeError(f"site {name!r} must be a TOML table")
        result.append(Site(name=name, **values))
    return result


def write_sites(items: list[Site], path: str | Path | None = None) -> Path:
    """Atomically replace the site manifest with normalized TOML."""
    target = Path(path).expanduser() if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for item in sorted(items, key=lambda value: value.name):
        lines.append(f"[sites.{json.dumps(item.name)}]")
        values = {
            "domain": item.domain,
            "host": item.host,
            "port": item.port,
            "scheme": item.scheme,
            "health_path": item.health_path,
            "tls": item.tls,
            "redirect_http": item.redirect_http,
            "cert_provider": item.cert_provider,
            "tls_certificate": item.tls_certificate,
            "tls_certificate_key": item.tls_certificate_key,
        }
        for key, value in values.items():
            if value is None:
                continue
            if isinstance(value, bool):
                encoded = "true" if value else "false"
            elif isinstance(value, int):
                encoded = str(value)
            else:
                encoded = json.dumps(str(value))
            lines.append(f"{key} = {encoded}")
        lines.append("")

    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
