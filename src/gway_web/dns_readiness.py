"""Authoritative DNS readiness checks used during public exposure."""

from __future__ import annotations

import ipaddress
import shutil
import subprocess
import time

import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rdatatype

# Start iterative lookups at root authorities so readiness never depends on the
# host resolver's cached view of an authoritative nameserver hostname.
_ROOT_HINTS = ("198.41.0.4", "192.33.4.12")
_PER_QUERY_TIMEOUT = 2.0
_MAX_DELEGATION_DEPTH = 24


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


def _remaining(deadline: float) -> float:
    """Return the non-negative number of seconds left before ``deadline``."""
    return max(0.0, deadline - time.monotonic())


def _normalize_address(value: str) -> str | None:
    """Normalize one IP literal, returning ``None`` for invalid input."""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _answer_addresses(response) -> tuple[str, ...]:
    """Return normalized A addresses from a DNS response answer section."""
    addresses: list[str] = []
    for rrset in response.answer:
        if rrset.rdtype != dns.rdatatype.A:
            continue
        for item in rrset:
            raw = getattr(item, "address", None)
            if not isinstance(raw, str):
                continue
            normalized = _normalize_address(raw)
            if normalized is not None and normalized not in addresses:
                addresses.append(normalized)
    return tuple(addresses)


def _query_response(name: str, rdtype: int, nameserver: str, *, deadline: float):
    """Query one server without recursion while honoring a shared deadline."""
    remaining = _remaining(deadline)
    if remaining <= 0:
        return None

    query = dns.message.make_query(name, rdtype)
    query.flags &= ~dns.flags.RD
    try:
        response = dns.query.udp(
            query,
            nameserver,
            timeout=min(_PER_QUERY_TIMEOUT, remaining),
        )
        if response.flags & dns.flags.TC:
            remaining = _remaining(deadline)
            if remaining <= 0:
                return None
            response = dns.query.tcp(
                query,
                nameserver,
                timeout=min(_PER_QUERY_TIMEOUT, remaining),
            )
    except (dns.exception.DNSException, OSError):
        return None
    return response


def _referral(response) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Extract delegated NS names and any A glue from one DNS referral."""
    names: list[str] = []
    for rrset in response.authority:
        if rrset.rdtype != dns.rdatatype.NS:
            continue
        for item in rrset:
            target = str(item.target).rstrip(".").lower()
            if target and target not in names:
                names.append(target)

    glue_lists: dict[str, list[str]] = {name: [] for name in names}
    for rrset in response.additional:
        if rrset.rdtype != dns.rdatatype.A:
            continue
        owner = str(rrset.name).rstrip(".").lower()
        if owner not in glue_lists:
            continue
        for item in rrset:
            raw = getattr(item, "address", None)
            if not isinstance(raw, str):
                continue
            normalized = _normalize_address(raw)
            if normalized is not None and normalized not in glue_lists[owner]:
                glue_lists[owner].append(normalized)

    return tuple(names), {name: tuple(values) for name, values in glue_lists.items()}


def _iterative_addresses(
    name: str,
    *,
    deadline: float,
    resolving: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Resolve an A record iteratively from root authorities under one deadline."""
    normalized_name = name.rstrip(".").lower()
    if not normalized_name or normalized_name in resolving or _remaining(deadline) <= 0:
        return ()

    current_servers = list(_ROOT_HINTS)
    resolving = resolving | {normalized_name}
    for _ in range(_MAX_DELEGATION_DEPTH):
        if _remaining(deadline) <= 0:
            return ()
        advanced = False
        for server in current_servers:
            response = _query_response(
                normalized_name,
                dns.rdatatype.A,
                server,
                deadline=deadline,
            )
            if response is None:
                continue
            if response.flags & dns.flags.AA:
                return _answer_addresses(response)

            names, glue = _referral(response)
            if not names:
                continue

            next_servers: list[str] = []
            for delegated_name in names:
                delegated_addresses = glue.get(delegated_name, ())
                if not delegated_addresses:
                    delegated_addresses = _iterative_addresses(
                        delegated_name,
                        deadline=deadline,
                        resolving=resolving,
                    )
                for address in delegated_addresses:
                    if address not in next_servers:
                        next_servers.append(address)
            if next_servers:
                current_servers = next_servers
                advanced = True
                break
        if not advanced:
            return ()
    return ()


def _authoritative_nameservers(
    fqdn: str,
    *,
    deadline: float,
) -> dict[str, tuple[str, ...]]:
    """Discover the current delegated authorities for ``fqdn`` from the root."""
    current: dict[str, tuple[str, ...]] = {".": _ROOT_HINTS}
    normalized_fqdn = fqdn.rstrip(".").lower()

    for _ in range(_MAX_DELEGATION_DEPTH):
        if _remaining(deadline) <= 0:
            return {}
        referral_found = False
        for endpoints in current.values():
            for endpoint in endpoints:
                response = _query_response(
                    normalized_fqdn,
                    dns.rdatatype.A,
                    endpoint,
                    deadline=deadline,
                )
                if response is None:
                    continue
                if response.flags & dns.flags.AA:
                    return current

                names, glue = _referral(response)
                if not names:
                    continue

                delegated: dict[str, tuple[str, ...]] = {}
                for delegated_name in names:
                    addresses = glue.get(delegated_name, ())
                    if not addresses:
                        addresses = _iterative_addresses(
                            delegated_name,
                            deadline=deadline,
                        )
                    if addresses:
                        delegated[delegated_name] = addresses
                if delegated:
                    current = delegated
                    referral_found = True
                    break
            if referral_found:
                break
        if not referral_found:
            return {}
    return {}


def _query_a(fqdn: str, nameserver: str, *, timeout: float) -> tuple[str, ...]:
    """Return authoritative A records from one nameserver endpoint."""
    if timeout <= 0:
        return ()
    deadline = time.monotonic() + timeout
    response = _query_response(
        fqdn,
        dns.rdatatype.A,
        nameserver,
        deadline=deadline,
    )
    if response is None or not response.flags & dns.flags.AA:
        return ()
    return _answer_addresses(response)


def authoritative_addresses(fqdn: str, *, timeout: float = 2.0) -> tuple[str, ...]:
    """Return A records currently served by every delegated authority for ``fqdn``.

    Authoritative server endpoints are discovered iteratively from root DNS
    delegation rather than through the host resolver. The supplied ``timeout``
    is a total budget shared by delegation discovery and all authority queries.
    """
    if timeout <= 0:
        return ()

    deadline = time.monotonic() + timeout
    authorities = _authoritative_nameservers(fqdn, deadline=deadline)
    if not authorities:
        return ()

    per_authority: list[set[str]] = []
    for endpoints in authorities.values():
        observed: set[str] = set()
        for endpoint in endpoints:
            remaining = _remaining(deadline)
            if remaining <= 0:
                return ()
            observed.update(
                _query_a(
                    fqdn,
                    endpoint,
                    timeout=min(_PER_QUERY_TIMEOUT, remaining),
                )
            )
        if not observed:
            return ()
        per_authority.append(observed)

    common = set(per_authority[0])
    for observed in per_authority[1:]:
        common.intersection_update(observed)
    return tuple(sorted(common))
