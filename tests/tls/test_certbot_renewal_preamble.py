from pathlib import Path

import pytest

from gway_web.certbot import _renewal_authenticator


def test_renewal_authenticator_accepts_certbot_metadata_preamble(tmp_path: Path) -> None:
    renewal = tmp_path / "register.example.com.conf"
    renewal.write_text(
        "# renew_before_expiry = 30 days\n"
        "version = 1.21.0\n"
        "archive_dir = /etc/letsencrypt/archive/register.example.com\n"
        "cert = /etc/letsencrypt/live/register.example.com/cert.pem\n"
        "privkey = /etc/letsencrypt/live/register.example.com/privkey.pem\n"
        "chain = /etc/letsencrypt/live/register.example.com/chain.pem\n"
        "fullchain = /etc/letsencrypt/live/register.example.com/fullchain.pem\n"
        "\n"
        "[renewalparams]\n"
        "account = account-id\n"
        "authenticator = webroot\n"
        "server = https://acme-v02.api.letsencrypt.org/directory\n",
        encoding="utf-8",
    )

    assert _renewal_authenticator(renewal) == "webroot"


def test_renewal_authenticator_still_rejects_malformed_preamble(tmp_path: Path) -> None:
    renewal = tmp_path / "broken.conf"
    renewal.write_text(
        "this is not certbot metadata\n"
        "[renewalparams]\n"
        "authenticator = webroot\n",
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="section headers"):
        _renewal_authenticator(renewal)
