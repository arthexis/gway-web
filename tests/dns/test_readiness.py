from __future__ import annotations

from types import SimpleNamespace

import dns.flags
import dns.message
import dns.rrset

from gway_web import dns_readiness, exposure
from gway_web.public_dns import DNSRecord


def test_flush_local_cache_uses_resolvectl_when_available(monkeypatch) -> None:
    """Use resolvectl when systemd-resolved cache control is available."""
    calls = []
    monkeypatch.setattr(dns_readiness.shutil, "which", lambda command: "/usr/bin/resolvectl")

    def fake_run(command, **kwargs):
        """Record the cache-flush subprocess invocation."""
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dns_readiness.subprocess, "run", fake_run)

    assert dns_readiness.flush_local_cache() is True
    assert calls[0][0] == ["/usr/bin/resolvectl", "flush-caches"]


def test_query_a_rejects_non_authoritative_answer(monkeypatch) -> None:
    """Ignore A records when the responding endpoint does not set AA."""
    query = dns.message.make_query("logs.example.com", "A")
    response = dns.message.make_response(query)
    response.flags &= ~dns.flags.AA
    response.answer.append(
        dns.rrset.from_text("logs.example.com.", 60, "IN", "A", "203.0.113.10")
    )
    monkeypatch.setattr(
        dns_readiness,
        "_query_response",
        lambda *args, **kwargs: response,
    )

    assert (
        dns_readiness._query_a("logs.example.com", "192.0.2.1", timeout=1.0)
        == ()
    )


def test_authoritative_addresses_requires_every_nameserver_to_agree(monkeypatch) -> None:
    """Return only addresses shared by every currently delegated authority."""
    monkeypatch.setattr(
        dns_readiness,
        "_authoritative_nameservers",
        lambda fqdn, deadline: {
            "ns1.example.com": ("192.0.2.1",),
            "ns2.example.com": ("192.0.2.2",),
        },
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
    """Treat one stale delegated authority as a not-ready DNS state."""
    monkeypatch.setattr(
        dns_readiness,
        "_authoritative_nameservers",
        lambda fqdn, deadline: {
            "ns1.example.com": ("192.0.2.1",),
            "ns2.example.com": ("192.0.2.2",),
        },
    )
    monkeypatch.setattr(
        dns_readiness,
        "_query_a",
        lambda fqdn, server, timeout: (
            ("203.0.113.10",) if server == "192.0.2.1" else ()
        ),
    )

    assert dns_readiness.authoritative_addresses("logs.example.com") == ()


def test_authoritative_addresses_zero_budget_avoids_dns_io(monkeypatch) -> None:
    """Return immediately when the authoritative lookup has no time budget."""
    called = False

    def discover(fqdn, deadline):
        """Fail the test if zero-budget discovery performs DNS work."""
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(dns_readiness, "_authoritative_nameservers", discover)

    assert dns_readiness.authoritative_addresses("logs.example.com", timeout=0.0) == ()
    assert called is False


class _FakeProvider:
    """Minimal public-DNS provider for exposure orchestration tests."""

    def __init__(self) -> None:
        self.records_value: list[DNSRecord] = []

    def records(self, name: str, record_type: str | None = None):
        """Return the current in-memory record set."""
        return list(self.records_value)

    def ensure_record(self, record: DNSRecord):
        """Append one record to the in-memory record set."""
        self.records_value.append(record)
        return record

    def replace_records(self, name: str, record_type: str, records):
        """Replace the in-memory record set."""
        self.records_value = list(records)


def test_wait_public_dns_forwards_remaining_deadline(monkeypatch) -> None:
    """Forward a zero caller budget instead of starting a fresh DNS timeout."""
    budgets: list[float] = []

    def public_addresses(fqdn: str, *, timeout: float) -> tuple[str, ...]:
        """Record the attempt budget supplied by the propagation waiter."""
        budgets.append(timeout)
        return ()

    monkeypatch.setattr(exposure, "_public_dns_addresses", public_addresses)

    result = exposure._wait_public_dns(
        "logs.example.com",
        "203.0.113.10",
        timeout=0.0,
    )

    assert result["ok"] is False
    assert result["attempts"] == 1
    assert budgets == [0.0]


def test_new_dns_record_flushes_local_cache_before_wait(monkeypatch) -> None:
    """Flush local resolver state before polling authoritative DNS readiness."""
    provider = _FakeProvider()
    calls: list[str] = []
    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: object())
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: None)
    monkeypatch.setattr(
        exposure,
        "flush_local_cache",
        lambda: calls.append("flush") or True,
    )

    def wait_for_dns(fqdn, address, timeout):
        """Record that the DNS wait follows the cache flush."""
        calls.append("wait")
        return {
            "ok": True,
            "fqdn": fqdn,
            "expected": address,
            "observed": [address],
            "attempts": 1,
            "elapsed_seconds": 0.0,
        }

    monkeypatch.setattr(exposure, "_wait_public_dns", wait_for_dns)
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
    assert calls == ["flush", "wait"]
