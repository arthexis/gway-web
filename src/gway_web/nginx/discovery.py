"""Read-only discovery of an Nginx installation layout."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NginxLayout:
    """Describe the conventional filesystem layout used by an Nginx install."""

    executable: Path
    config_root: Path
    nginx_conf: Path
    sites_available: Path
    sites_enabled: Path
    conf_d: Path


def discover_nginx(
    *,
    executable: str | Path | None = None,
    config_root: str | Path | None = None,
) -> NginxLayout:
    """Return an Nginx layout without mutating or validating host configuration."""

    if executable is None:
        resolved = shutil.which("nginx")
        if resolved is None:
            raise FileNotFoundError("nginx executable was not found on PATH")
        executable_path = Path(resolved)
    else:
        executable_path = Path(executable)

    root = Path(config_root) if config_root is not None else Path("/etc/nginx")
    return NginxLayout(
        executable=executable_path,
        config_root=root,
        nginx_conf=root / "nginx.conf",
        sites_available=root / "sites-available",
        sites_enabled=root / "sites-enabled",
        conf_d=root / "conf.d",
    )
