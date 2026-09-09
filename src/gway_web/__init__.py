"""Portable web deployment capabilities for GWAY."""

from .health import HealthResult, health, status
from .registry import clear, get, load, register, sites, unregister
from .serve import serve
from .site import Site, upstream_url, url

__all__ = [
    "HealthResult",
    "Site",
    "__version__",
    "clear",
    "get",
    "health",
    "load",
    "register",
    "serve",
    "sites",
    "status",
    "unregister",
    "upstream_url",
    "url",
]

__version__ = "0.1.0"
