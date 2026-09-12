"""Provider-neutral public DNS record management."""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class PublicDNSProviderError(RuntimeError):
    """Raised when a public DNS provider operation fails."""


@dataclass(frozen=True, slots=True)
class DNSRecord:
    """One ordinary public DNS record."""

    name: str
    type: str
    value: str
    ttl: int = 600

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("DNS record name cannot be empty")
        if self.type.upper() not in {"A", "AAAA", "CNAME"}:
            raise ValueError(f"unsupported public DNS record type: {self.type}")
        if not self.value.strip():
            raise ValueError("DNS record value cannot be empty")
        if self.ttl < 1:
            raise ValueError("DNS record TTL must be positive")


class PublicDNSProvider(Protocol):
    """Minimal ordinary-record capability required by public exposure."""

    def records(self, name: str, record_type: str | None = None) -> Collection[DNSRecord]: ...

    def ensure_record(self, record: DNSRecord) -> DNSRecord: ...

    def replace_records(
        self, name: str, record_type: str, records: Collection[DNSRecord]
    ) -> None: ...

    def delete_record(self, record: DNSRecord) -> None: ...


class GoDaddyPublicDNSProvider:
    """Manage ordinary records in one explicitly configured GoDaddy zone."""

    def __init__(
        self,
        *,
        zone: str,
        key: str,
        secret: str,
        api_base: str = "https://api.godaddy.com/v1",
        timeout: float = 10.0,
    ) -> None:
        self.zone = zone.strip().lower().rstrip(".")
        if not self.zone or not key or not secret:
            raise ValueError("GoDaddy zone, key, and secret are required")
        self.key = key
        self.secret = secret
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _relative_name(self, fqdn: str) -> str:
        name = fqdn.strip().lower().rstrip(".")
        if name == self.zone:
            return "@"
        suffix = f".{self.zone}"
        if not name.endswith(suffix):
            raise ValueError(f"{fqdn!r} is outside configured DNS zone {self.zone!r}")
        return name[: -len(suffix)]

    def _url(self, name: str, record_type: str) -> str:
        relative = self._relative_name(name)
        return (
            f"{self.api_base}/domains/{quote(self.zone, safe='')}/records/"
            f"{quote(record_type.upper(), safe='')}/{quote(relative, safe='')}"
        )

    def _request(
        self,
        method: str,
        name: str,
        record_type: str,
        payload: object | None = None,
    ) -> object | None:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self._url(name, record_type),
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"sso-key {self.key}:{self.secret}",
                "User-Agent": "gway-web/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                raw = response.read()
        except HTTPError as exc:
            raise PublicDNSProviderError(
                f"GoDaddy DNS request failed with HTTP {exc.code}"
            ) from exc
        except (URLError, OSError) as exc:
            raise PublicDNSProviderError("GoDaddy DNS request failed") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PublicDNSProviderError("GoDaddy DNS returned invalid JSON") from exc

    def records(self, name: str, record_type: str | None = None) -> list[DNSRecord]:
        if record_type is None:
            result: list[DNSRecord] = []
            for kind in ("A", "AAAA", "CNAME"):
                result.extend(self.records(name, kind))
            return result
        kind = record_type.upper()
        payload = self._request("GET", name, kind)
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise PublicDNSProviderError("GoDaddy DNS returned an invalid record list")
        result = []
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("data"), str):
                raise PublicDNSProviderError("GoDaddy DNS returned an invalid record")
            ttl = item.get("ttl", 600)
            if not isinstance(ttl, int):
                raise PublicDNSProviderError("GoDaddy DNS returned an invalid TTL")
            result.append(DNSRecord(name=name, type=kind, value=item["data"], ttl=ttl))
        return result

    def replace_records(
        self, name: str, record_type: str, records: Collection[DNSRecord]
    ) -> None:
        kind = record_type.upper()
        values = list(records)
        if not values:
            self._request("DELETE", name, kind)
            return
        payload = [{"data": item.value, "ttl": item.ttl} for item in values]
        self._request("PUT", name, kind, payload)

    def ensure_record(self, record: DNSRecord) -> DNSRecord:
        current = list(self.records(record.name, record.type))
        if any(item.value == record.value for item in current):
            return next(item for item in current if item.value == record.value)
        self.replace_records(record.name, record.type, [*current, record])
        return record

    def delete_record(self, record: DNSRecord) -> None:
        current = list(self.records(record.name, record.type))
        remaining = [item for item in current if item.value != record.value]
        if len(remaining) == len(current):
            return
        self.replace_records(record.name, record.type, remaining)
