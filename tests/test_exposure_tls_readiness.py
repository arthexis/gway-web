from __future__ import annotations

from gway_web import exposure


def test_wait_public_tls_retries_transient_stale_certificate(monkeypatch) -> None:
    calls = []
    results = iter(
        [
            {
                "ok": False,
                "fqdn": "register.example.com",
                "address": "203.0.113.10",
                "error": "certificate verify failed: hostname mismatch",
            },
            {
                "ok": True,
                "fqdn": "register.example.com",
                "address": "203.0.113.10",
            },
        ]
    )

    def fake_public_tls(fqdn, timeout, public_address=None):
        calls.append((fqdn, timeout, public_address))
        return next(results)

    monkeypatch.setattr(exposure, "_public_tls", fake_public_tls)
    monkeypatch.setattr(exposure.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(exposure.time, "sleep", lambda delay: None)

    result = exposure._wait_public_tls(
        "register.example.com",
        5.0,
        "203.0.113.10",
        readiness_timeout=1.0,
        retry_interval=0.25,
    )

    assert result["ok"] is True
    assert len(calls) == 2
    assert calls[0] == ("register.example.com", 5.0, "203.0.113.10")


def test_wait_public_tls_returns_last_failure_after_deadline(monkeypatch) -> None:
    calls = []

    def fake_public_tls(fqdn, timeout, public_address=None):
        calls.append((fqdn, timeout, public_address))
        return {
            "ok": False,
            "fqdn": fqdn,
            "address": public_address,
            "error": "certificate verify failed",
        }

    monkeypatch.setattr(exposure, "_public_tls", fake_public_tls)
    monkeypatch.setattr(exposure.time, "monotonic", lambda: 10.0)

    result = exposure._wait_public_tls(
        "register.example.com",
        5.0,
        "203.0.113.10",
        readiness_timeout=0.0,
    )

    assert result["ok"] is False
    assert len(calls) == 1
