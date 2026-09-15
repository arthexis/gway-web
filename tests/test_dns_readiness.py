from __future__ import annotations

from types import SimpleNamespace

from gway_web import dns_readiness, exposure
from gway_web.public_dns import DNSRecord


def test_flush_local_cache_uses_resolvectl_when_available(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(dns_readiness.shutil, "which", lambda command: "/usr/bin/resolvectl")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dns_readiness.subprocess, "run", fake_run)

    assert dns_readiness.flush_local_cache() is True
    assert calls[0][0] == ["/usr/bin/resolvectl", "flush-caches"]


def test_authoritative_addresses_requires_every_nameserver_to_agree(monkeypatch) -> None:
    monkeypatch.setattr(
        dns_readiness.dns.resolver,
        "zone_for_name",
        lambda fqdn: "example.com.",
    )
    monkeypatch.setattr(
        dns_readiness.dns.resolver,
        "resolve",
        lambda *args, **kwargs: [
            SimpleNamespace(target="ns1.example.com."),
            SimpleNamespace(target="ns2.example.com."),
        ],
    )
    monkeypatch.setattr(
        dns_readiness,
        "_nameserver_addresses",
        lambda name: {
            "ns1.example.com": ("192.0.2.1",),
            "ns2.example.com": ("192.0.2.2",),
        }[name],
    )
    answers = {
        "192.0.2.1": ("203.0.113.10", "198.51.100.4"),
        "192.0.2.2": ("203.0.113.10",),
    }
    monkeypatch.setattr(
        dns_readiness,
        "_query_a",
        lambda fqdn, server, timeout: answers[server],
    )

    assert dns_readiness.authoritative_addresses("logs.example.com") == ("203.0.113.10",)


def test_authoritative_addresses_not_ready_when_one_nameserver_is_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        dns_readiness.dns.resolver,
        "zone_for_name",
        lambda fqdn: "example.com.",
    )
    monkeypatch.setattr(
        dns_readiness.dns.resolver,
        "resolve",
        lambda *args, **kwargs: [
            SimpleNamespace(target="ns1.example.com."),
            SimpleNamespace(target="ns2.example.com."),
        ],
    )
    monkeypatch.setattr(
        dns_readiness,
        "_nameserver_addresses",
        lambda name: {
            "ns1.example.com": ("192.0.2.1",),
            "ns2.example.com": ("192.0.2.2",),
        }[name],
    )
    monkeypatch.setattr(
        dns_readiness,
        "_query_a",
        lambda fqdn, server, timeout: (
            ("203.0.113.10",) if server == "192.0.2.1" else ()
        ),
    )

    assert dns_readiness.authoritative_addresses("logs.example.com") == ()


class _FakeProvider:
    def __init__(self) -> None:
        self.records_value: list[DNSRecord] = []

    def records(self, name: str, record_type: str | None = None):
        return list(self.records_value)

    def ensure_record(self, record: DNSRecord):
        self.records_value.append(record)
        return record

    def replace_records(self, name: str, record_type: str, records):
        self.records_value = list(records)


def test_new_dns_record_flushes_local_cache_before_wait(monkeypatch) -> None:
    provider = _FakeProvider()
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: object())
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: None)
    monkeypatch.setattr(exposure, "flush_local_cache", lambda: True)
    monkeypatch.setattr(
        exposure,
        "_wait_public_dns",
        lambda fqdn, address, timeout: {
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
        "_wait_public_tls",
        lambda fqdn, timeout, public_address=None: {"ok": True},
    )
    monkeypatch.setattr(
        exposure,
        "_public_health",
        lambda site, timeout, public_address=None: {"ok": True},
    )
    monkeypatch.setattr(exposure, "_persist", lambda target: None)

    result = exposure.ensure(
        fqdn="logs.example.com",
        upstream="http://127.0.0.1:8040",
        dns_provider="godaddy",
        dns_zone="example.com",
        public_address="203.0.113.10",
    )

    assert result["dns"]["local_cache_flushed"] is True
