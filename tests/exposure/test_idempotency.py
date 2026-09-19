from __future__ import annotations

from types import SimpleNamespace

import pytest

from gway_web import exposure


def _healthy_tls(fqdn: str, timeout: float, public_address=None):
    return {"ok": True, "fqdn": fqdn, "address": public_address}


def _healthy_public(site, timeout: float, public_address=None):
    return {
        "ok": True,
        "url": f"{site.url}{site.health_path}",
        "address": public_address,
        "status": 200,
    }


def test_repeated_managed_exposure_is_a_noop(monkeypatch) -> None:
    exposed = []
    persisted = []
    snapshots = []
    renewals = []

    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        exposure,
        "certificate_status",
        lambda fqdn: SimpleNamespace(state="managed", ready=True),
    )
    monkeypatch.setattr(exposure, "certbot_renew", lambda *args, **kwargs: renewals.append(args))
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: snapshots.append(site))
    monkeypatch.setattr(exposure, "nginx_expose", exposed.append)
    monkeypatch.setattr(exposure, "_public_tls", _healthy_tls)
    monkeypatch.setattr(exposure, "_public_health", _healthy_public)
    monkeypatch.setattr(exposure, "_persist", persisted.append)

    result = exposure.ensure(
        fqdn="register.example.com",
        upstream="http://127.0.0.1:8787",
    )

    assert result["success"] is True
    assert result["changed"] is False
    assert exposed == []
    assert snapshots == []
    assert renewals == []
    assert persisted[0].tls is True


def test_managed_certificate_repairs_tls_without_http_teardown(monkeypatch) -> None:
    exposed = []
    probes = iter(
        [
            {"ok": False, "fqdn": "register.example.com", "error": "wrong certificate"},
            {"ok": True, "fqdn": "register.example.com"},
        ]
    )

    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        exposure,
        "certificate_status",
        lambda fqdn: SimpleNamespace(state="managed", ready=True),
    )
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: pytest.fail("rollback is opt-in"))
    monkeypatch.setattr(exposure, "nginx_expose", exposed.append)
    monkeypatch.setattr(exposure, "_public_tls", lambda *args, **kwargs: next(probes))
    monkeypatch.setattr(exposure, "_public_health", _healthy_public)
    monkeypatch.setattr(exposure, "_persist", lambda site: None)

    result = exposure.ensure(
        fqdn="register.example.com",
        upstream="http://127.0.0.1:8787",
    )

    assert result["success"] is True
    assert result["changed"] is True
    assert len(exposed) == 1
    assert exposed[0].tls is True


def test_missing_certificate_uses_http_bootstrap(monkeypatch) -> None:
    exposed = []

    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        exposure,
        "certificate_status",
        lambda fqdn: SimpleNamespace(state="missing", ready=False),
    )
    monkeypatch.setattr(exposure, "nginx_expose", exposed.append)
    monkeypatch.setattr(
        exposure,
        "certbot_obtain",
        lambda site, email, agree_tos: SimpleNamespace(state="managed", ready=True),
    )
    monkeypatch.setattr(exposure, "_public_tls", _healthy_tls)
    monkeypatch.setattr(exposure, "_public_health", _healthy_public)
    monkeypatch.setattr(exposure, "_persist", lambda site: None)

    result = exposure.ensure(
        fqdn="register.example.com",
        upstream="http://127.0.0.1:8787",
        email="ops@example.com",
    )

    assert result["success"] is True
    assert [site.tls for site in exposed] == [False, True]


def test_rollback_remains_available_when_explicitly_enabled(monkeypatch) -> None:
    state = object()
    restored = []

    monkeypatch.setattr(exposure, "_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        exposure,
        "certificate_status",
        lambda fqdn: SimpleNamespace(state="managed", ready=True),
    )
    monkeypatch.setattr(exposure, "nginx_snapshot", lambda site: state)
    monkeypatch.setattr(exposure, "nginx_expose", lambda site: None)
    monkeypatch.setattr(exposure, "nginx_restore", restored.append)
    monkeypatch.setattr(
        exposure,
        "_public_tls",
        lambda *args, **kwargs: {"ok": False, "error": "wrong certificate"},
    )
    monkeypatch.setattr(
        exposure,
        "_wait_public_tls",
        lambda *args, **kwargs: {"ok": False, "error": "still wrong"},
    )

    with pytest.raises(RuntimeError, match="public TLS check failed"):
        exposure.ensure(
            fqdn="register.example.com",
            upstream="http://127.0.0.1:8787",
            rollback=True,
        )

    assert restored == [state]
