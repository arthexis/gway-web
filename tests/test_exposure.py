from __future__ import annotations

from types import SimpleNamespace

import pytest

from gway_web import exposure
from gway_web.public_dns import DNSRecord


class FakeProvider:
    def __init__(self, records: list[DNSRecord] | None = None) -> None:
        self._records = list(records or [])
        self.replacements: list[list[DNSRecord]] = []

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
        self.replacements.append(list(records))

    def delete_record(self, record: DNSRecord):
        self._records = [item for item in self._records if item != record]


def _patch_live_success(monkeypatch) -> None:
    monkeypatch.setattr(
        exposure,
        "_public_tls",
        lambda fqdn, timeout: {"ok": True, "fqdn": fqdn},
    )


def test_ensure_uses_exact_fqdn_and_persists_only_after_public_health(monkeypatch) -> None:
    provider = FakeProvider([DNSRecord("register.example.com", "A", "203.0.113.10")])
    exposed = []
    persisted = []
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: exposed.append(site) or None)
    monkeypatch.setattr(exposure, "nginx_disable", lambda site: None)
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
    _patch_live_success(monkeypatch)
    monkeypatch.setattr(
        exposure,
        "_public_health",
        lambda site, timeout: {"ok": True, "url": f"{site.url}/health", "status": 200},
    )
    monkeypatch.setattr(exposure, "_persist", persisted.append)

    result = exposure.ensure(
        fqdn="register.example.com",
        upstream="http://127.0.0.1:8787",
        dns_provider="godaddy",
        dns_zone="example.com",
    )

    assert result["success"] is True
    assert result["fqdn"] == "register.example.com"
    assert result["tls"]["ok"] is True
    assert [item.domain for item in exposed] == ["register.example.com", "register.example.com"]
    assert persisted[0].domain == "register.example.com"
    assert persisted[0].host == "127.0.0.1"
    assert persisted[0].port == 8787


def test_ensure_restores_dns_and_does_not_persist_on_public_failure(monkeypatch) -> None:
    original = DNSRecord("register.example.com", "A", "203.0.113.10")
    provider = FakeProvider([original])
    persisted = []
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: None)
    monkeypatch.setattr(exposure, "nginx_disable", lambda site: None)
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
    _patch_live_success(monkeypatch)
    monkeypatch.setattr(
        exposure,
        "_public_health",
        lambda site, timeout: {"ok": False, "status": 503},
    )
    monkeypatch.setattr(exposure, "_persist", persisted.append)

    with pytest.raises(RuntimeError, match="public health check failed"):
        exposure.ensure(
            fqdn="register.example.com",
            upstream="http://127.0.0.1:8787",
            dns_provider="godaddy",
            dns_zone="example.com",
            public_address="198.51.100.9",
        )

    assert persisted == []
    assert provider.records("register.example.com", "A") == [original]


def test_ensure_refuses_to_persist_when_live_tls_is_invalid(monkeypatch) -> None:
    persisted = []
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: None)
    monkeypatch.setattr(exposure, "nginx_disable", lambda site: None)
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
        "_public_tls",
        lambda fqdn, timeout: {"ok": False, "fqdn": fqdn, "error": "expired"},
    )
    monkeypatch.setattr(exposure, "_persist", persisted.append)

    with pytest.raises(RuntimeError, match="public TLS check failed"):
        exposure.ensure(
            fqdn="register.example.com",
            upstream="http://127.0.0.1:8787",
        )
    assert persisted == []


def test_ensure_requires_address_only_for_new_dns_record(monkeypatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    with pytest.raises(ValueError, match="public_address is required"):
        exposure.ensure(
            fqdn="register.example.com",
            upstream="http://127.0.0.1:8787",
            dns_provider="godaddy",
            dns_zone="example.com",
        )
