from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from gway_web import commands
from gway_web.config import read_sites


def test_gway_command_surface_is_compact():
    public = {
        name
        for name, function in inspect.getmembers(commands, inspect.isfunction)
        if not name.startswith("_") and function.__module__ == commands.__name__
    }

    assert public == {"certificate", "check", "reload", "serve", "site", "stop"}


def test_site_create_get_update_and_views(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = tmp_path / "web.toml"
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(config))

    created = commands.site(
        "arthexis",
        create=True,
        domain="example.com",
        port=8069,
        certbot=True,
    )

    assert created.name == "arthexis"
    assert created.cert_provider == "certbot"
    assert created.tls is True
    assert created.tls_certificate == Path("/etc/letsencrypt/live/example.com/fullchain.pem")
    assert commands.site("arthexis", url=True) == "https://example.com"
    assert commands.site("arthexis", upstream=True) == "http://127.0.0.1:8069"

    updated = commands.site("arthexis", update=True, port=8070)
    assert updated.port == 8070
    assert updated.domain == "example.com"
    assert read_sites(config)[0].port == 8070


def test_site_name_with_dots_and_dashes_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = tmp_path / "web.toml"
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(config))

    name = "api-v2.example.com"
    created = commands.site(name, create=True, domain="api-v2.example.com", port=9000)

    assert created.name == name
    assert commands.site(name).name == name
    assert read_sites(config)[0].name == name
    assert '[sites."api-v2.example.com"]' in config.read_text()


def test_site_requires_explicit_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(tmp_path / "web.toml"))

    with pytest.raises(ValueError, match="--create or --update"):
        commands.site("arthexis", port=8070)


def test_certificate_provider_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(tmp_path / "web.toml"))

    item = commands.site(
        "example",
        create=True,
        domain="example.com",
        certificate_provider="certbot",
    )
    assert item.cert_provider == "certbot"

    with pytest.raises(ValueError, match="disagree"):
        commands.site(
            "other",
            create=True,
            domain="other.example.com",
            cert_provider="manual",
            certificate_provider="certbot",
        )
