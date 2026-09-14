from __future__ import annotations

import pytest

from gway_web.public_dns import (
    DNSRecord,
    GoDaddyPublicDNSProvider,
    PublicDNSProviderError,
)


def _provider() -> GoDaddyPublicDNSProvider:
    return GoDaddyPublicDNSProvider(zone="example.com", key="key", secret="secret")


def test_ensure_record_reads_back_written_record(monkeypatch) -> None:
    active = _provider()
    calls: list[tuple[str, object | None]] = []
    responses = iter(
        [
            [],
            None,
            [{"data": "203.0.113.10", "ttl": 600}],
        ]
    )

    def request(method, name, record_type, payload=None):
        calls.append((method, payload))
        return next(responses)

    monkeypatch.setattr(active, "_request", request)

    result = active.ensure_record(DNSRecord("logs.example.com", "A", "203.0.113.10"))

    assert result == DNSRecord("logs.example.com", "A", "203.0.113.10")
    assert [method for method, _payload in calls] == ["GET", "PUT", "GET"]


def test_ensure_record_fails_when_godaddy_does_not_read_back_write(monkeypatch) -> None:
    active = _provider()
    responses = iter([[], None, []])
    monkeypatch.setattr(
        active,
        "_request",
        lambda method, name, record_type, payload=None: next(responses),
    )

    with pytest.raises(PublicDNSProviderError, match="did not confirm A record"):
        active.ensure_record(DNSRecord("logs.example.com", "A", "203.0.113.10"))
