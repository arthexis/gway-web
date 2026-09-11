"""Transactional host operations for GWAY-managed Nginx sites."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ..site import Site
from .discovery import NginxLayout, discover_nginx
from .render import render_http_proxy


def test(layout: NginxLayout | None = None) -> None:
    """Validate the active Nginx configuration."""

    layout = layout or discover_nginx()
    subprocess.run(
        [str(layout.executable), "-t", "-c", str(layout.nginx_conf)],
        check=True,
    )


def reload(layout: NginxLayout | None = None) -> None:
    """Reload Nginx after validating its active configuration."""

    layout = layout or discover_nginx()
    test(layout)
    _reload(layout)


def expose(site: Site, *, layout: NginxLayout | None = None) -> Path:
    """Stage, validate, and atomically activate a generated site configuration."""

    layout = layout or discover_nginx()
    target = layout.sites_available / _site_filename(site)
    enabled = layout.sites_enabled / target.name
    rendered = render_http_proxy(site)

    target.parent.mkdir(parents=True, exist_ok=True)
    enabled.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_bytes() if target.exists() else None
    previous_enabled = _snapshot_entry(enabled)

    _atomic_write(target, rendered)
    _atomic_symlink(target, enabled)

    def rollback() -> None:
        _restore_file(target, previous)
        _restore_entry(enabled, previous_enabled)

    _activate(layout, rollback)
    return target


def enable(site: Site, *, layout: NginxLayout | None = None) -> Path:
    """Enable an already generated site and validate before reloading."""

    layout = layout or discover_nginx()
    target = layout.sites_available / _site_filename(site)
    if not target.is_file():
        raise FileNotFoundError(f"site configuration does not exist: {target}")
    enabled = layout.sites_enabled / target.name
    previous_enabled = _snapshot_entry(enabled)
    _atomic_symlink(target, enabled)
    _activate(layout, lambda: _restore_entry(enabled, previous_enabled))
    return enabled


def disable(site: Site, *, layout: NginxLayout | None = None) -> Path:
    """Disable a site, validating the remaining configuration before reload."""

    layout = layout or discover_nginx()
    enabled = layout.sites_enabled / _site_filename(site)
    previous_enabled = _snapshot_entry(enabled)
    if enabled.exists() or enabled.is_symlink():
        enabled.unlink()
    _activate(layout, lambda: _restore_entry(enabled, previous_enabled))
    return enabled


def _activate(layout: NginxLayout, rollback: Callable[[], None]) -> None:
    """Validate and reload, restoring the previous state if either step fails."""

    try:
        test(layout)
        _reload(layout)
    except Exception:
        rollback()
        try:
            test(layout)
            _reload(layout)
        except (subprocess.SubprocessError, OSError):
            # Preserve the activation error. The restored files remain the source of truth
            # even if Nginx itself cannot currently be reloaded.
            return
        raise


def _reload(layout: NginxLayout) -> None:
    """Signal Nginx to reload without performing a second validation."""

    subprocess.run([str(layout.executable), "-s", "reload"], check=True)


def _site_filename(site: Site) -> str:
    name = site.name.strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("site name is not safe for an Nginx configuration filename")
    return f"gway-{name}.conf"


def _atomic_write(path: Path, content: str) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_symlink(target: Path, link: Path) -> None:
    temporary = link.with_name(f".{link.name}.new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def _restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    _atomic_write_bytes(path, previous)


def _snapshot_entry(path: Path) -> tuple[str, bytes | Path | None]:
    if path.is_symlink():
        return ("symlink", path.readlink())
    if path.exists():
        return ("file", path.read_bytes())
    return ("missing", None)


def _restore_entry(path: Path, previous: tuple[str, bytes | Path | None]) -> None:
    kind, value = previous
    path.unlink(missing_ok=True)
    if kind == "symlink":
        assert isinstance(value, Path)
        path.symlink_to(value)
    elif kind == "file":
        assert isinstance(value, bytes)
        _atomic_write_bytes(path, value)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.restore.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
