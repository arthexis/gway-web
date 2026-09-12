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


def _patch_nginx_transaction(monkeypatch):
    state = object()
    restored = []
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: state)
    monkeypatch.setattr(exposure, "nginx_restore", restored.append)
    return state, restored


def _patch_live_success(monkeypatch) -> None:
    monkeypatch.setattr(
        exposure,
        "_public_tls",
        lambda fqdn, timeout, public_address=None: {
            "ok": True,
            "fqdn": fqdn,
            "address": public_address,
        },
    )


def test_dependency_exposure_rejects_non_loopback_upstream() -> None:
    with pytest.raises(ValueError, match="loopback upstream"):
        exposure._site_for(
            "register.example.com",
            "http://10.0.0.5:8787",
            "/health",
            tls=False,
        )


def test_ensure_uses_exact_fqdn_and_persists_only_after_public_health(monkeypatch) -> None:
    provider = FakeProvider([DNSRecord("register.example.com", "A", "203.0.113.10")])
    exposed = []
    persisted = []
    _patch_nginx_transaction(monkeypatch)
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: exposed.append(site) or None)
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
        lambda site, timeout, public_address=None: {
            "ok": True,
            "url": f"{site.url}/health",
            "address": public_address,
            "status": 200,
        },
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


def test_ensure_restores_dns_and_nginx_on_public_failure(monkeypatch) -> None:
    original = DNSRecord("register.example.com", "A", "203.0.113.10")
    provider = FakeProvider([original])
    persisted = []
    state, restored = _patch_nginx_transaction(monkeypatch)
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
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
    _patch_live_success(monkeypatch)
    monkeypatch.setattr(
        exposure,
        "_public_health",
        lambda site, timeout, public_address=None: {
            "ok": False,
            "address": public_address,
            "status": 503,
        },
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
    assert restored == [state]


def test_invalid_upstream_is_rejected_before_dns_mutation(monkeypatch) -> None:
    provider = FakeProvider([DNSRecord("register.example.com", "A", "203.0.113.10")])
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    with pytest.raises(ValueError, match="loopback upstream"):
        exposure.ensure(
            fqdn="register.example.com",
            upstream="http://10.0.0.5:8787",
            dns_provider="godaddy",
            dns_zone="example.com",
            public_address="198.51.100.9",
        )
    assert provider.records("register.example.com", "A") == [
        DNSRecord("register.example.com", "A", "203.0.113.10")
    ]


def test_ensure_refuses_to_persist_when_live_tls_is_invalid(monkeypatch) -> None:
    persisted = []
    _patch_nginx_transaction(monkeypatch)
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: None)
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
        "_public_tls",
        lambda fqdn, timeout, public_address=None: {
            "ok": False,
            "fqdn": fqdn,
            "address": public_address,
            "error": "expired",
        },
    )
    monkeypatch.setattr(exposure, "_persist", persisted.append)

    with pytest.raises(RuntimeError, match="public TLS check failed"):
        exposure.ensure(
            fqdn="register.example.com",
            upstream="http://127.0.0.1:8787",
        )
    assert persisted == []


def test_check_folds_live_tls_failure_into_certificate_readiness(monkeypatch) -> None:
    site = exposure._site_for(
        "register.example.com",
        "http://127.0.0.1:8787",
        "/health",
        tls=True,
    )
    monkeypatch.setattr(exposure, "read_sites", lambda: [site])
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        exposure,
        "site_check",
        lambda name, timeout: [{"check": "certificate", "ok": True, "state": "managed"}],
    )
    monkeypatch.setattr(
        exposure,
        "_public_tls",
        lambda fqdn, timeout, public_address=None: {
            "ok": False,
            "fqdn": fqdn,
            "address": public_address,
            "error": "expired",
        },
    )
    monkeypatch.setattr(
        exposure,
        "_public_health",
        lambda site, timeout, public_address=None: {
            "ok": False,
            "address": public_address,
            "status": None,
            "error": "expired",
        },
    )

    result = exposure.check(fqdn="register.example.com")
    certificate = next(item for item in result["checks"] if item["check"] == "certificate")

    assert result["ok"] is False
    assert certificate["ok"] is False
    assert certificate["live_tls"]["error"] == "expired"


def test_ensure_requires_address_only_for_new_dns_record(monkeypatch) -> None:
    provider = FakeProvider()
    _patch_nginx_transaction(monkeypatch)
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    with pytest.raises(ValueError, match="public_address is required"):
        exposure.ensure(
            fqdn="register.example.com",
            upstream="http://127.0.0.1:8787",
            dns_provider="godaddy",
            dns_zone="example.com",
        )


def test_release_reports_partial_dns_failure(monkeypatch) -> None:
    site = exposure._site_for(
        "register.example.com",
        "http://127.0.0.1:8787",
        "/health",
        tls=True,
    )
    provider = FakeProvider([DNSRecord("register.example.com", "A", "203.0.113.10")])
    monkeypatch.setattr(exposure, "read_sites", lambda: [site])
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda target: object())
    monkeypatch.setattr(exposure, "nginx_disable", lambda target: None)
    monkeypatch.setattr(exposure, "write_sites", lambda sites: None)
    monkeypatch.setattr(exposure, "clear_registry", lambda: None)
    monkeypatch.setattr(
        provider,
        "delete_record",
        lambda record: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    result = exposure.release(
        fqdn="register.example.com",
        dns_provider="godaddy",
        dns_zone="example.com",
        public_address="203.0.113.10",
    )

    assert result["released"] is False
    assert result["partial"] is True
    assert result["local_released"] is True
    assert result["stage"] == "dns"
