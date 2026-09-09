"""Read-only reachability and HTTP health checks."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .registry import resolve
from .site import Site


@dataclass(frozen=True, slots=True)
class HealthResult:
    """Result of an HTTP health probe."""

    ok: bool
    url: str
    status_code: int | None
    elapsed_ms: float
    error: str | None = None


def status(site: Site | str, *, timeout: float = 2.0) -> bool:
    """Return whether the site's host/port accepts a TCP connection."""
    target = resolve(site)
    try:
        with socket.create_connection((target.host, target.port), timeout=timeout):
            return True
    except OSError:
        return False


def health(site: Site | str, *, timeout: float = 5.0) -> HealthResult:
    """Probe the site's direct HTTP health endpoint without mutating the host."""
    target = resolve(site)
    started = monotonic()
    request = Request(target.health_url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            code = response.getcode()
            return HealthResult(
                ok=200 <= code < 400,
                url=target.health_url,
                status_code=code,
                elapsed_ms=(monotonic() - started) * 1000,
            )
    except HTTPError as exc:
        return HealthResult(
            ok=False,
            url=target.health_url,
            status_code=exc.code,
            elapsed_ms=(monotonic() - started) * 1000,
            error=str(exc),
        )
    except (URLError, OSError) as exc:
        return HealthResult(
            ok=False,
            url=target.health_url,
            status_code=None,
            elapsed_ms=(monotonic() - started) * 1000,
            error=str(exc),
        )
