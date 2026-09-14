from __future__ import annotations

from types import SimpleNamespace

import pytest

from gway_web import exposure
from gway_web.public_dns import DNSRecord


class FakeProvider:
    def __init__(self, records: list[DNSRecord] | None = None) -> None:
        self._records = list(records or [])

    def records(self, name: str, record_type: str | None = None):
        return [
            item
            for item in self._records
            if item.name == name and (record_type is None or item.type == record_type)
        ]

    def ensure_record(self, record: DNSRecord):
        if not any(item.value == record.value for item in self._records):
            self._records.append(record)
        return record

    def replace_records(self, name: str, record_type: str, records):
        self._records = [
            item for item in self._records if not (item.name == name and item.type == record_type)
        ] + list(records)


def _timeout_dns(monkeypatch) -> None:
    monkeypatch.setattr(
        exposure,
        "_wait_public_dns",
        lambda fqdn, address, timeout=300.0, retry_interval=2.0: {
            "ok": False,
            "fqdn": fqdn,
            "expected": address,
            "observed": [],
            "attempts": 2,
            "elapsed_seconds": timeout,
        },
    )


def test_no_dns_rollback_preserves_record_after_propagation_timeout(monkeypatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: object())
    _timeout_dns(monkeypatch)

    with pytest.raises(RuntimeError, match="public DNS propagation timed out"):
        exposure.ensure(
            fqdn="logs.example.com",
            upstream="http://127.0.0.1:8040",
            dns_provider="godaddy",
            dns_zone="example.com",
            public_address="203.0.113.10",
            dns_wait_timeout=1.0,
            dns_rollback=False,
        )

    assert provider.records("logs.example.com", "A") == [
        DNSRecord("logs.example.com", "A", "203.0.113.10")
    ]


def test_no_rollback_disables_dns_and_nginx_rollback(monkeypatch) -> None:
    original = DNSRecord("logs.example.com", "A", "203.0.113.10")
    replacement = DNSRecord("logs.example.com", "A", "198.51.100.20")
    provider = FakeProvider([original])
    restored = []
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: object())
    monkeypatch.setattr(exposure, "nginx_restore", restored.append)
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: None)
    monkeypatch.setattr(
        exposure,
        "certificate_status",
        lambda fqdn: SimpleNamespace(state="managed", ready=True),
    )
    monkeypatch.setattr(
        exposure,
        "certbot_renew",
        lambda fqdn, deploy_hook=None: SimpleNamespace(state="managed", ready=True),
    )
    monkeypatch.setattr(
        exposure,
        "_wait_public_dns",
        lambda fqdn, address, timeout=300.0, retry_interval=2.0: {
            "ok": True,
            "fqdn": fqdn,
            "expected": address,
            "observed": [address],
            "attempts": 1,
            "elapsed_seconds": 0.0,
        },
    )
    monkeypatch.setattr(
        exposure,
        "_wait_public_tls",
        lambda fqdn, timeout, public_address=None: {"ok": True},
    )
    monkeypatch.setattr(
        exposure,
        "_public_health",
        lambda site, timeout, public_address=None: {"ok": False, "status": 503},
    )

    with pytest.raises(RuntimeError, match="public health check failed"):
        exposure.ensure(
            fqdn="logs.example.com",
            upstream="http://127.0.0.1:8040",
            dns_provider="godaddy",
            dns_zone="example.com",
            public_address=replacement.value,
            rollback=False,
        )

    assert provider.records("logs.example.com", "A") == [original, replacement]
    assert restored == []


def test_global_no_rollback_overrides_dns_rollback_true(monkeypatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: object())
    _timeout_dns(monkeypatch)

    with pytest.raises(RuntimeError, match="public DNS propagation timed out"):
        exposure.ensure(
            fqdn="logs.example.com",
            upstream="http://127.0.0.1:8040",
            dns_provider="godaddy",
            dns_zone="example.com",
            public_address="203.0.113.10",
            rollback=False,
            dns_rollback=True,
        )

    assert provider.records("logs.example.com", "A") == [
        DNSRecord("logs.example.com", "A", "203.0.113.10")
    ]
