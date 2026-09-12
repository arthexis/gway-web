from pathlib import Path

from gway_web.certbot import CertificateStatus, renew


def test_renew_reuses_ready_managed_certificate_when_deploy_hook_is_disabled(
    tmp_path, monkeypatch
) -> None:
    live = tmp_path / "live" / "register.example.com"
    live.mkdir(parents=True)
    certificate = live / "fullchain.pem"
    key = live / "privkey.pem"
    certificate.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    renewal = tmp_path / "renewal.conf"
    renewal.write_text("version = 1.21.0\n", encoding="utf-8")
    status = CertificateStatus(
        domain="register.example.com",
        certificate=certificate,
        key=key,
        renewal_config=renewal,
        state="managed",
    )

    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: status)
    monkeypatch.setattr(
        "gway_web.certbot._renewal_authenticator",
        lambda path: (_ for _ in ()).throw(AssertionError("renewal config should not be parsed")),
    )
    monkeypatch.setattr(
        "gway_web.certbot.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("certbot should not run")),
    )

    result = renew("register.example.com", deploy_hook=None)

    assert result is status


def test_explicit_renewal_still_reads_authenticator_and_runs_certbot(
    tmp_path, monkeypatch
) -> None:
    live = tmp_path / "live" / "example.com"
    live.mkdir(parents=True)
    certificate = live / "fullchain.pem"
    key = live / "privkey.pem"
    certificate.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    renewal = tmp_path / "renewal.conf"
    renewal.write_text("[renewalparams]\nauthenticator = webroot\n", encoding="utf-8")
    status = CertificateStatus(
        domain="example.com",
        certificate=certificate,
        key=key,
        renewal_config=renewal,
        state="managed",
    )
    calls = []

    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: status)
    monkeypatch.setattr("gway_web.certbot.discover_certbot", lambda executable=None: Path("/bin/certbot"))
    monkeypatch.setattr("gway_web.certbot.subprocess.run", lambda command, check: calls.append(command))

    result = renew("example.com")

    assert result is status
    assert calls
    assert calls[0][:4] == ["/bin/certbot", "renew", "--cert-name", "example.com"]
