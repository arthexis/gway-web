"""Portable web deployment capabilities for GWAY."""

from .certbot import (
    CertificateStatus,
    ChallengeResult,
    DNSHooks,
    certificate_status as certbot_status,
    challenge as certbot_challenge,
    discover_certbot,
    obtain as certbot_obtain,
    obtain_dns as certbot_obtain_dns,
    renew as certbot_renew,
)
from .config import config_path, read_sites
from .dns import (
    DNSChallenge,
    DNSPropagation,
    DNSProvider,
    challenge_name as dns_challenge_name,
    cleanup as dns_cleanup,
    present as dns_present,
    propagation_status as dns_propagation_status,
    wait_for_propagation as dns_wait_for_propagation,
)
from .health import HealthResult, health, status
from .nginx import disable, enable, expose, reload, test
from .registry import clear, get, load, load_config, register, resolve, sites, unregister
from .serve import serve
from .site import Site, site, upstream_url, url

__all__ = [
    "CertificateStatus",
    "ChallengeResult",
    "DNSChallenge",
    "DNSHooks",
    "DNSPropagation",
    "DNSProvider",
    "HealthResult",
    "Site",
    "__version__",
    "certbot_challenge",
    "certbot_obtain",
    "certbot_obtain_dns",
    "certbot_renew",
    "certbot_status",
    "clear",
    "config_path",
    "disable",
    "discover_certbot",
    "dns_challenge_name",
    "dns_cleanup",
    "dns_present",
    "dns_propagation_status",
    "dns_wait_for_propagation",
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
