"""Authoritative DNS readiness checks used during public exposure."""

from __future__ import annotations

import ipaddress
import shutil
import socket
import subprocess

import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rdatatype
import dns.resolver


def flush_local_cache() -> bool:
    """Best-effort flush of systemd-resolved without making it a dependency."""
    command = shutil.which("resolvectl")
    if command is None:
        return False
    try:
        result = subprocess.run(
            [command, "flush-caches"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _nameserver_addresses(name: str) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(name, 53, type=socket.SOCK_DGRAM)
    except OSError:
        return ()

    addresses: list[str] = []
    for answer in answers:
        raw = answer[4][0]
        try:
            normalized = str(ipaddress.ip_address(raw))
        except ValueError:
            continue
        if normalized not in addresses:
            addresses.append(normalized)
    return tuple(addresses)


def _query_a(fqdn: str, nameserver: str, *, timeout: float) -> tuple[str, ...]:
    query = dns.message.make_query(fqdn, dns.rdatatype.A)
    query.flags &= ~dns.flags.RD
    try:
        response = dns.query.udp(query, nameserver, timeout=timeout)
        if response.flags & dns.flags.TC:
            response = dns.query.tcp(query, nameserver, timeout=timeout)
    except (dns.exception.DNSException, OSError):
        return ()

    addresses: list[str] = []
    for rrset in response.answer:
        if rrset.rdtype != dns.rdatatype.A:
            continue
        for item in rrset:
            raw = getattr(item, "address", None)
            if not isinstance(raw, str):
                continue
            try:
                normalized = str(ipaddress.ip_address(raw))
            except ValueError:
                continue
            if normalized not in addresses:
                addresses.append(normalized)
    return tuple(addresses)


def authoritative_addresses(fqdn: str, *, timeout: float = 2.0) -> tuple[str, ...]:
    """Return A records present on every authoritative nameserver for ``fqdn``.

    The zone and NS hostnames may be discovered through the configured recursive
    resolver, but the target A record itself is queried directly from each
    authoritative server. This prevents local or upstream negative caches for a
    newly-created name from blocking readiness.
    """
    try:
        zone = dns.resolver.zone_for_name(fqdn)
        ns_answer = dns.resolver.resolve(zone, dns.rdatatype.NS, search=False, lifetime=timeout)
    except (dns.exception.DNSException, OSError):
        return ()

    nameservers = [str(item.target).rstrip(".") for item in ns_answer]
    if not nameservers:
        return ()

    per_authority: list[set[str]] = []
    for nameserver in nameservers:
        observed: set[str] = set()
        for address in _nameserver_addresses(nameserver):
            observed.update(_query_a(fqdn, address, timeout=timeout))
        per_authority.append(observed)

    common = per_authority[0]
    for observed in per_authority[1:]:
        common &= observed
    return tuple(sorted(common))
