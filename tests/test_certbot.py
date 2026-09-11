from pathlib import Path

import pytest

from gway_web.certbot import (
    CertificateStatus,
    certificate_status,
    challenge,
    discover_certbot,
    obtain,
    renew,
)
from gway_web.site import Site


def _status(tmp_path: Path, *, state: str = "managed", authenticator: str = "webroot"):
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
        state=state,
    )


def test_certificate_status_distinguishes_managed_stale_and_missing(tmp_path):
    live_root = tmp_path / "live"
    renewal_root = tmp_path / "renewal"
    domain = "example.com"

    missing = certificate_status(domain, live_root=live_root, renewal_root=renewal_root)
    assert missing.state == "missing"

    live = live_root / domain
    live.mkdir(parents=True)
    (live / "fullchain.pem").write_text("certificate", encoding="utf-8")
    (live / "privkey.pem").write_text("key", encoding="utf-8")
    stale = certificate_status(domain, live_root=live_root, renewal_root=renewal_root)
    assert stale.state == "stale"
    assert stale.ready is True

    renewal_root.mkdir()
    (renewal_root / f"{domain}.conf").write_text("[renewalparams]\n", encoding="utf-8")
    managed = certificate_status(domain, live_root=live_root, renewal_root=renewal_root)
    assert managed.state == "managed"
    assert managed.managed is True


def test_discover_certbot_has_install_guidance(monkeypatch):
    monkeypatch.setattr("gway_web.certbot.shutil.which", lambda candidate: None)

    with pytest.raises(FileNotFoundError, match="apt install certbot"):
        discover_certbot()


def test_obtain_uses_certonly_webroot_and_verifies_material(tmp_path, monkeypatch):
    result = _status(tmp_path)
    calls = []
    statuses = [
        CertificateStatus(
            domain="example.com",
            certificate=tmp_path / "missing" / "fullchain.pem",
            key=tmp_path / "missing" / "privkey.pem",
            renewal_config=tmp_path / "missing.conf",
            state="missing",
        ),
        result,
    ]
    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: statuses.pop(0))
    monkeypatch.setattr("gway_web.certbot.discover_certbot", lambda executable=None: Path("/bin/certbot"))
    monkeypatch.setattr("gway_web.certbot.subprocess.run", lambda command, check: calls.append(command))

    obtained = obtain(
        Site(name="web", domain="example.com"),
        email="admin@example.com",
        agree_tos=True,
        webroot=tmp_path / "webroot",
    )

    assert obtained == result
    command = calls[0]
    assert command[:3] == ["/bin/certbot", "certonly", "--webroot"]
    assert "--cert-name" in command
    assert "--nginx" not in command
    assert "install" not in command


def test_obtain_refuses_stale_live_directory(tmp_path, monkeypatch):
    stale = _status(tmp_path, state="stale")
    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: stale)

    with pytest.raises(RuntimeError, match="stale Certbot live directory"):
        obtain(
            Site(name="web", domain="example.com"),
            email="admin@example.com",
            agree_tos=True,
            webroot=tmp_path / "webroot",
        )


def test_renew_requires_webroot_authenticator_and_uses_reload_hook(tmp_path, monkeypatch):
    status = _status(tmp_path)
    calls = []
    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: status)
    monkeypatch.setattr("gway_web.certbot.discover_certbot", lambda executable=None: Path("/bin/certbot"))
    monkeypatch.setattr("gway_web.certbot.subprocess.run", lambda command, check: calls.append(command))

    renewed = renew("example.com")

    assert renewed == status
    assert calls == [
        [
            "/bin/certbot",
            "renew",
            "--cert-name",
            "example.com",
            "--non-interactive",
            "--deploy-hook",
            "gway web reload",
        ]
    ]


def test_renew_refuses_non_webroot_renewal(tmp_path, monkeypatch):
    status = _status(tmp_path, authenticator="nginx")
    monkeypatch.setattr("gway_web.certbot.certificate_status", lambda domain: status)

    with pytest.raises(RuntimeError, match="expected 'webroot'"):
        renew("example.com")


def test_challenge_compares_public_response_to_local_file(tmp_path, monkeypatch):
    webroot = tmp_path / "webroot"
    challenge_file = webroot / ".well-known" / "acme-challenge" / "token"
    challenge_file.parent.mkdir(parents=True)
    challenge_file.write_text("proof", encoding="utf-8")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"proof"

        def getcode(self):
            return 200

    monkeypatch.setattr("gway_web.certbot.urlopen", lambda request, timeout: Response())

    result = challenge(Site(name="web", domain="example.com"), "token", webroot=webroot)

    assert result.ok is True
    assert result.local_exists is True
    assert result.body_matches is True
    assert result.url == "http://example.com/.well-known/acme-challenge/token"
