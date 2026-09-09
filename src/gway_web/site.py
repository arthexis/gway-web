"""Portable description of a web application."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlunsplit


@dataclass(frozen=True, slots=True)
class Site:
    """Describe a web application without binding it to a proxy implementation."""

    name: str
    domain: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    scheme: str = "http"
    health_path: str = "/"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("site name cannot be empty")
        if not self.host.strip():
            raise ValueError("site host cannot be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("site port must be between 1 and 65535")
        if self.scheme not in {"http", "https"}:
            raise ValueError("site scheme must be 'http' or 'https'")
        if not self.health_path.startswith("/"):
            raise ValueError("health_path must start with '/'")

    @property
    def upstream_url(self) -> str:
        """Return the application's direct host/port URL."""
        return _build_url(self.scheme, self.host, self.port)

    @property
    def url(self) -> str:
        """Return the externally meaningful URL when a domain is configured."""
        if self.domain:
            return _build_url(self.scheme, self.domain, None)
        return self.upstream_url

    @property
    def health_url(self) -> str:
        """Return the direct application health URL."""
        return f"{self.upstream_url}{self.health_path}"


def _build_url(scheme: str, host: str, port: int | None) -> str:
    normalized_host = host
    if ":" in host and not host.startswith("["):
        normalized_host = f"[{host}]"
    authority = normalized_host if port is None else f"{normalized_host}:{port}"
    return urlunsplit((scheme, authority, "", "", ""))


def url(site: Site) -> str:
    """Return the canonical URL for *site*."""
    return site.url


def upstream_url(site: Site) -> str:
    """Return the direct application URL for *site*."""
    return site.upstream_url
