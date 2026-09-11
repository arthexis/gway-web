"""Provider-neutral DNS challenge operations for ACME DNS-01."""

from __future__ import annotations

from collections.abc import Collection, Callable
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Protocol, runtime_checkable


@runtime_checkable
class DNSProvider(Protocol):
    """Minimal TXT-record capability implemented by external DNS providers."""

    def create_txt(self, name: str, value: str) -> None:
        """Create a TXT value without replacing unrelated values."""
        ...

    def remove_txt(self, name: str, value: str) -> None:
        """Remove only the TXT value previously created for the challenge."""
        ...

    def txt_values(self, name: str) -> Collection[str]:
        """Return currently observable TXT values for a record name."""
        ...


@dataclass(frozen=True, slots=True)
class DNSChallenge:
    """One DNS-01 TXT record requested by an ACME challenge."""

    domain: str
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class DNSPropagation:
    """Observed propagation state for a DNS-01 TXT value."""

    challenge: DNSChallenge
    present: bool
    attempts: int
    elapsed_seconds: float
    observed_values: tuple[str, ...]


def challenge_name(domain: str) -> str:
    """Return the DNS-01 TXT name for a normal or wildcard domain."""

    base = _base_domain(domain)
    return f"_acme-challenge.{base}"


def present(provider: DNSProvider, domain: str, value: str) -> DNSChallenge:
    """Create the TXT value for a DNS-01 challenge through an external provider."""

    if not value:
        raise ValueError("DNS challenge value cannot be empty")
    challenge = DNSChallenge(domain=domain, name=challenge_name(domain), value=value)
    provider.create_txt(challenge.name, challenge.value)
    return challenge


def cleanup(provider: DNSProvider, challenge: DNSChallenge) -> None:
    """Remove only the TXT value associated with a completed challenge."""

    provider.remove_txt(challenge.name, challenge.value)


def propagation_status(provider: DNSProvider, challenge: DNSChallenge) -> DNSPropagation:
    """Inspect whether a challenge value is currently visible through the provider."""

    values = tuple(provider.txt_values(challenge.name))
    return DNSPropagation(
        challenge=challenge,
        present=challenge.value in values,
        attempts=1,
        elapsed_seconds=0.0,
        observed_values=values,
    )


def wait_for_propagation(
    provider: DNSProvider,
    challenge: DNSChallenge,
    *,
    timeout: float = 120.0,
    interval: float = 2.0,
    sleep_fn: Callable[[float], None] = sleep,
    clock: Callable[[], float] = monotonic,
) -> DNSPropagation:
    """Poll provider-visible TXT values until the challenge appears or timeout expires."""

    if timeout < 0:
        raise ValueError("timeout cannot be negative")
    if interval <= 0:
        raise ValueError("interval must be positive")

    started = clock()
    attempts = 0
    values: tuple[str, ...] = ()
    while True:
        attempts += 1
        values = tuple(provider.txt_values(challenge.name))
        elapsed = clock() - started
        if challenge.value in values:
            return DNSPropagation(
                challenge=challenge,
                present=True,
                attempts=attempts,
                elapsed_seconds=elapsed,
                observed_values=values,
            )
        if elapsed >= timeout:
            return DNSPropagation(
                challenge=challenge,
                present=False,
                attempts=attempts,
                elapsed_seconds=elapsed,
                observed_values=values,
            )
        sleep_fn(min(interval, max(0.0, timeout - elapsed)))


def _base_domain(domain: str) -> str:
    if not domain or domain in {".", ".."}:
        raise ValueError("domain is not safe for a DNS challenge")
    base = domain.removeprefix("*.")
    if not base or "/" in base or "\\" in base or any(character.isspace() for character in base):
        raise ValueError("domain is not safe for a DNS challenge")
    if "*" in base:
        raise ValueError("wildcard is only allowed as the leading '*.' label")
    return base
