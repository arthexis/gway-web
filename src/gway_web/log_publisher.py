from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .tokens import issue_token

CredentialIssuer = Callable[..., dict[str, object]]


@dataclass(frozen=True)
class WebPublisherBinding:
    """Provider-owned publisher binding compatible with GWAY's wire contract."""

    provider: str
    destination: str
    configuration: Mapping[str, object] = field(default_factory=dict)
    environment: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_record(self) -> dict[str, object]:
        """Return the JSON-compatible binding record consumed by GWAY core."""
        return {
            "provider": self.provider,
            "destination": self.destination,
            "configuration": dict(self.configuration),
            "environment": dict(self.environment),
            "metadata": dict(self.metadata),
        }


class WebLogPublisherProvider:
    """Provision Web-specific log publisher bindings for GWAY consumers."""

    name = "web"

    def __init__(self, *, credential_issuer: CredentialIssuer = issue_token) -> None:
        self._credential_issuer = credential_issuer

    @staticmethod
    def _loopback_host(host: str | None) -> bool:
        if host is None:
            return False
        normalized = host.rstrip(".").casefold()
        if normalized == "localhost" or normalized.endswith(".localhost"):
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    @classmethod
    def _destination(cls, value: str) -> str:
        destination = value.rstrip("/")
        parsed = urlparse(destination)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Web log publisher destination must be an HTTP(S) URL")
        if parsed.scheme == "http" and not cls._loopback_host(parsed.hostname):
            raise ValueError("Web log publisher HTTP destinations must be loopback")
        return destination

    def provision(
        self,
        *,
        destination: str,
        consumer: str,
        service: object | None = None,
        current: object | None = None,
    ) -> WebPublisherBinding:
        """Create a Web ingest binding; W2 will own reuse/rotation decisions."""
        del service, current
        destination = self._destination(destination)
        credential = self._credential_issuer(
            name=f"gway-consumer:{consumer}",
            scopes="logs:ingest",
        )
        token = credential.get("token")
        token_id = credential.get("token_id")
        if not isinstance(token, str) or not token:
            raise ValueError("Web log publisher credential issuer returned no token")
        if not isinstance(token_id, str) or not token_id:
            raise ValueError("Web log publisher credential issuer returned no token id")

        return WebPublisherBinding(
            provider=self.name,
            destination=destination,
            configuration={
                "transport": "http",
                "url_template": f"{destination}/api/logs/{{run_id}}/events",
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer {GWAY_WEB_LOG_TOKEN}",
                    "Content-Type": "application/x-ndjson",
                },
            },
            environment={"GWAY_WEB_LOG_TOKEN": token},
            metadata={"token_id": token_id},
        )


__all__ = ["WebLogPublisherProvider", "WebPublisherBinding"]
