"""Site registry and declarative discovery."""

from __future__ import annotations

from collections.abc import Iterable

from .config import read_sites
from .site import Site

_registry: dict[str, Site] = {}
_loaded_default = False


def register(site: Site, *, replace: bool = False) -> Site:
    """Register *site* by name and return it."""
    if site.name in _registry and not replace:
        raise ValueError(f"site already registered: {site.name}")
    _registry[site.name] = site
    return site


def unregister(name: str) -> Site:
    """Remove and return a registered site."""
    _ensure_default_loaded()
    try:
        return _registry.pop(name)
    except KeyError as exc:
        raise KeyError(f"unknown site: {name}") from exc


def get(name: str) -> Site:
    """Return a registered or declaratively configured site by name."""
    _ensure_default_loaded()
    try:
        return _registry[name]
    except KeyError as exc:
        raise KeyError(f"unknown site: {name}") from exc


def resolve(site: Site | str) -> Site:
    """Return a Site unchanged or resolve a site name."""
    return site if isinstance(site, Site) else get(site)


def sites() -> list[Site]:
    """Return known sites sorted by name."""
    _ensure_default_loaded()
    return [_registry[name] for name in sorted(_registry)]


def load(items: Iterable[Site], *, replace: bool = False) -> list[Site]:
    """Register a collection of sites and return the resulting registry."""
    for site in items:
        register(site, replace=replace)
    return sites()


def load_config(path: str, *, replace: bool = True) -> list[Site]:
    """Load site definitions from a TOML manifest."""
    for site in read_sites(path):
        register(site, replace=replace)
    return sites()


def clear() -> None:
    """Clear the registry and reset lazy default configuration loading."""
    global _loaded_default
    _registry.clear()
    _loaded_default = False


def _ensure_default_loaded() -> None:
    global _loaded_default
    if _loaded_default:
        return
    _loaded_default = True
    for site in read_sites():
        register(site, replace=True)
