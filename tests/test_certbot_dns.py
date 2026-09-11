from pathlib import Path

import pytest

from gway_web.certbot import CertificateStatus, DNSHooks, obtain_dns, renew


def _status(tmp_path: Path, *, authenticator: str = "manual") -> CertificateStatus:
    live = tmp_path / "live" / "example.com"
    live.mkdir(parents=True)
    certificate = live / "fullchain.pem"
    key = live / "privkey.pem"
    certificate.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    renewal = tmp_path / "renewal" / "example.com.conf"
    renewal.parent.mkdir(parents=True)
    renewal.write_text(
        f"[renewalparams]\nauthenticator = {authenticator}\n",
        encoding="utf-8",
    )
    return CertificateStatus(
        domain="example.com",
        certificate=certificate,
        key=key,
        renewal_config=renewal,
        state="managed",
    )


def test_obtain_dns_uses_manual_dns_hooks_and_supports_wildcards(tmp_path, monkeypatch):
    missing = CertificateStatus(
        domain="example.com",
        certificate=tmp_path / "missing" / "fullchain.pem",
        key=tmp_path / "missing" / "privkey.pem",
        renewal_config=tmp_path / "missing.conf",
        state="missing",
    )
    ready = _status(tmp_path)
    statuses = [missing, ready]
    calls = []
    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: statuses.pop(0))
    monkeypatch.setattr(
        "gway_web.certbot.discover_certbot", lambda executable=None: Path("/bin/certbot")
    )
    monkeypatch.setattr(
        "gway_web.certbot.subprocess.run", lambda command, check: calls.append(command)
    )

    result = obtain_dns(
        "*.example.com",
        email="admin@example.com",
        hooks=DNSHooks("gway dns auth", "gway dns cleanup"),
        agree_tos=True,
    )

    assert result == ready
    command = calls[0]
    assert command[:3] == ["/bin/certbot", "certonly", "--manual"]
    assert ["--preferred-challenges", "dns"] == command[3:5]
    assert "*.example.com" in command
    assert command[command.index("--cert-name") + 1] == "example.com"
    assert command[command.index("--manual-auth-hook") + 1] == "gway dns auth"
    assert command[command.index("--manual-cleanup-hook") + 1] == "gway dns cleanup"
    assert "--nginx" not in command


def test_dns_hooks_reject_multiline_commands():
    with pytest.raises(ValueError, match="single command line"):
        DNSHooks("first\nsecond", "cleanup")


def test_manual_renewal_requires_dns_hooks(tmp_path, monkeypatch):
    status = _status(tmp_path)
    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: status)

    with pytest.raises(RuntimeError, match="manual.*dns_hooks"):
        renew("example.com")


def test_manual_renewal_passes_provider_hooks_to_certbot(tmp_path, monkeypatch):
    status = _status(tmp_path)
    calls = []
    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: status)
    monkeypatch.setattr(
        "gway_web.certbot.discover_certbot", lambda executable=None: Path("/bin/certbot")
    )
    monkeypatch.setattr(
        "gway_web.certbot.subprocess.run", lambda command, check: calls.append(command)
    )

    renewed = renew(
        "example.com",
        dns_hooks=DNSHooks("gway dns auth", "gway dns cleanup"),
    )

    assert renewed == status
    command = calls[0]
    assert command[:4] == ["/bin/certbot", "renew", "--cert-name", "example.com"]
    assert command[command.index("--manual-auth-hook") + 1] == "gway dns auth"
    assert command[command.index("--manual-cleanup-hook") + 1] == "gway dns cleanup"
    assert command[command.index("--deploy-hook") + 1] == "gway web reload"
