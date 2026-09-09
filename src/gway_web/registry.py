"""In-process registry for web sites."""

from __future__ import annotations

from collections.abc import Iterable

from .site import Site

_registry: dict[str, Site] = {}


def register(site: Site, *, replace: bool = False) -> Site:
    """Register *site* by name and return it."""
    if site.name in _registry and not replace:
        raise ValueError(f"site already registered: {site.name}")
    _registry[site.name] = site
    return site


def unregister(name: str) -> Site:
    """Remove and return a registered site."""
    try:
        return _registry.pop(name)
    except KeyError as exc:
        raise KeyError(f"unknown site: {name}") from exc


def get(name: str) -> Site:
    """Return a registered site by name."""
    try:
        return _registry[name]
    except KeyError as exc:
        raise KeyError(f"unknown site: {name}") from exc


def sites() -> list[Site]:
    """Return registered sites sorted by name."""
    return [_registry[name] for name in sorted(_registry)]


def load(items: Iterable[Site], *, replace: bool = False) -> list[Site]:
    """Register a collection of sites and return the resulting registry."""
    for site in items:
        register(site, replace=replace)
    return sites()


def clear() -> None:
    """Clear the registry. Primarily useful for isolated callers and tests."""
    _registry.clear()
