"""TLS certificate attachment helpers."""

from __future__ import annotations

from pathlib import Path

from .site import Site

LETSENCRYPT_LIVE = Path("/etc/letsencrypt/live")


def certificate_paths(site: Site) -> tuple[Path, Path]:
    """Resolve attached certificate paths without creating or mutating certificates."""

    if not site.tls:
        raise ValueError("certificate paths are only defined for TLS sites")
    if site.tls_certificate is not None and site.tls_certificate_key is not None:
        return Path(site.tls_certificate), Path(site.tls_certificate_key)
    if not site.domain:
        raise ValueError("TLS sites need a domain or explicit certificate paths")
    _validate_certificate_directory_name(site.domain)
    root = LETSENCRYPT_LIVE / site.domain
    return root / "fullchain.pem", root / "privkey.pem"


def validate_certificate_files(site: Site) -> None:
    """Require the certificate material referenced by a TLS site to already exist."""

    if not site.tls:
        return
    certificate, key = certificate_paths(site)
    for label, path in (("certificate", certificate), ("certificate key", key)):
        if not path.is_file():
            raise FileNotFoundError(f"TLS {label} does not exist: {path}")


def _validate_certificate_directory_name(domain: str) -> None:
    if domain in {".", ".."} or "/" in domain or "\\" in domain:
        raise ValueError("domain is not safe for a certificate directory")
