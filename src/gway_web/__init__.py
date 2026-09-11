"""Portable web deployment capabilities for GWAY."""

from .certbot import (
    CertificateStatus,
    ChallengeResult,
    certificate_status as certbot_status,
    challenge as certbot_challenge,
    discover_certbot,
    obtain as certbot_obtain,
    renew as certbot_renew,
)
from .config import config_path, read_sites
from .health import HealthResult, health, status
from .nginx import disable, enable, expose, reload, test
from .registry import clear, get, load, load_config, register, resolve, sites, unregister
from .serve import serve
from .site import Site, site, upstream_url, url

__all__ = [
    "CertificateStatus",
    "ChallengeResult",
    "HealthResult",
    "Site",
    "__version__",
    "certbot_challenge",
    "certbot_obtain",
    "certbot_renew",
    "certbot_status",
    "clear",
    "config_path",
    "disable",
    "discover_certbot",
    "enable",
    "expose",
    "get",
    "health",
    "load",
    "load_config",
    "read_sites",
    "register",
    "reload",
    "resolve",
    "serve",
    "site",
    "sites",
    "status",
    "test",
    "unregister",
    "upstream_url",
    "url",
]

__version__ = "0.1.0"
