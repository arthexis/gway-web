from __future__ import annotations

import pytest

from gway_web.public_dns import DNSRecord, GoDaddyPublicDNSProvider


def provider(**kwargs) -> GoDaddyPublicDNSProvider:
    return GoDaddyPublicDNSProvider(
        zone="example.com",
        key="key",
        secret="secret",
        **kwargs,
    )


def test_godaddy_api_base_requires_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        provider(api_base="http://api.example.test/v1")


def test_replace_records_rejects_unsupported_type_before_request(monkeypatch) -> None:
    active = provider()
    calls = []
    monkeypatch.setattr(active, "_request", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(ValueError, match="unsupported"):
        active.replace_records("register.example.com", "MX", [])

    assert calls == []


def test_replace_records_rejects_mismatched_record_before_request(monkeypatch) -> None:
    active = provider()
    calls = []
    monkeypatch.setattr(active, "_request", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(ValueError, match="match destination"):
        active.replace_records(
            "register.example.com",
            "A",
            [DNSRecord("other.example.com", "A", "203.0.113.10")],
        )

    assert calls == []
