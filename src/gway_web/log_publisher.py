from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .log_publisher_state import (
    publisher_store_lock,
    read_publisher_store,
    write_publisher_store,
)
from .tokens import issue_token, verify_token

CredentialIssuer = Callable[..., dict[str, object]]
CredentialVerifier = Callable[..., bool]


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

    def __init__(
        self,
        *,
        credential_issuer: CredentialIssuer = issue_token,
        credential_verifier: CredentialVerifier = verify_token,
    ) -> None:
        self._credential_issuer = credential_issuer
        self._credential_verifier = credential_verifier

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

    @staticmethod
    def _record_key(consumer: str, destination: str) -> str:
        return f"{consumer.casefold()}\n{destination}"

    @classmethod
    def _binding_from_record(
        cls,
        record: Mapping[str, object],
    ) -> WebPublisherBinding | None:
        provider = record.get("provider")
        destination = record.get("destination")
        configuration = record.get("configuration", {})
        environment = record.get("environment", {})
        metadata = record.get("metadata", {})
        if (
            provider != cls.name
            or not isinstance(destination, str)
            or not isinstance(configuration, Mapping)
            or not isinstance(environment, Mapping)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in environment.items()
            )
            or not isinstance(metadata, Mapping)
        ):
            return None
        return WebPublisherBinding(
            provider=provider,
            destination=destination,
            configuration=dict(configuration),
            environment=dict(environment),
            metadata=dict(metadata),
        )

    def _binding_valid(
        self,
        binding: WebPublisherBinding,
        *,
        destination: str,
    ) -> bool:
        if binding.destination != destination:
            return False
        token = binding.environment.get("GWAY_WEB_LOG_TOKEN")
        token_id = binding.metadata.get("token_id")
        if not isinstance(token, str) or not token:
            return False
        if not isinstance(token_id, str) or not token_id:
            return False
        return self._credential_verifier(token, scope="logs:ingest")

    def _new_binding(self, *, destination: str, consumer: str) -> WebPublisherBinding:
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

    def provision(
        self,
        *,
        destination: str,
        consumer: str,
    ) -> WebPublisherBinding:
        """Reuse a valid provider-owned binding or rotate it when invalid."""
        destination = self._destination(destination)
        key = self._record_key(consumer, destination)
        with publisher_store_lock():
            records = read_publisher_store()
            stored = records.get(key)
            binding = (
                self._binding_from_record(stored)
                if isinstance(stored, Mapping)
                else None
            )
            if binding is not None and self._binding_valid(
                binding,
                destination=destination,
            ):
                return binding

            binding = self._new_binding(
                destination=destination,
                consumer=consumer,
            )
            records[key] = binding.to_record()
            write_publisher_store(records)
            return binding


__all__ = ["WebLogPublisherProvider", "WebPublisherBinding"]
