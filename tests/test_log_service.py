from __future__ import annotations

from gway_web import log_service


def test_log_service_uses_loopback_defaults(monkeypatch) -> None:
    called = []

    def fake_serve_logs() -> None:
        called.append(True)

    monkeypatch.setattr(log_service, "serve_logs", fake_serve_logs)

    log_service.main()

    assert called == [True]
