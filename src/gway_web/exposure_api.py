"""Public exposure facade that preserves declarative site identity."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import exposure
from .config import read_sites, write_sites
from .registry import clear as clear_registry
from .site import Site


def _normalized_domain(value: str) -> str:
    return value.strip().lower().rstrip(".")


def _site_for_domain(fqdn: str) -> Site | None:
    target = _normalized_domain(fqdn)
    return next(
        (
            item
            for item in read_sites()
            if item.domain is not None and _normalized_domain(item.domain) == target
        ),
        None,
    )


def _rename_domain_site(fqdn: str, name: str) -> None:
    """Rename the configured site for ``fqdn`` without changing its web intent."""

    target_domain = _normalized_domain(fqdn)
    sites = read_sites()
    updated: list[Site] = []
    found = False
    for item in sites:
        same_domain = (
            item.domain is not None
            and _normalized_domain(item.domain) == target_domain
        )
        if same_domain:
            updated.append(replace(item, name=name))
            found = True
            continue
        if item.name == name:
            continue
        updated.append(item)
    if found:
        write_sites(updated)
        clear_registry()


def ensure(**kwargs: Any) -> dict[str, object]:
    """Expose an FQDN while retaining an existing logical site name for its domain."""

    fqdn = str(kwargs["fqdn"])
    existing = _site_for_domain(fqdn)
    result = exposure.ensure(**kwargs)
    if existing is not None and existing.name != _normalized_domain(fqdn):
        _rename_domain_site(fqdn, existing.name)
    return result


def check(**kwargs: Any) -> dict[str, object]:
    """Check an exposed FQDN regardless of whether its site has a logical name."""

    return exposure.check(**kwargs)


def release(**kwargs: Any) -> dict[str, object]:
    """Release an exposed FQDN while supporting preserved logical site names."""

    fqdn = str(kwargs["fqdn"])
    existing = _site_for_domain(fqdn)
    original_name = existing.name if existing is not None else None
    target_name = _normalized_domain(fqdn)
    renamed = existing is not None and original_name != target_name
    if renamed:
        _rename_domain_site(fqdn, target_name)

    try:
        result = exposure.release(**kwargs)
    except Exception:
        if renamed and _site_for_domain(fqdn) is not None and original_name is not None:
            _rename_domain_site(fqdn, original_name)
        raise

    if (
        renamed
        and not result.get("released")
        and _site_for_domain(fqdn) is not None
        and original_name is not None
    ):
        _rename_domain_site(fqdn, original_name)
    return result
