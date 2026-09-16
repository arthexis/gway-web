from __future__ import annotations

import pytest

from gway_web import exposure_api
from gway_web.config import read_sites, write_sites
from gway_web.site import Site


def _site(name: str, domain: str, *, tls: bool = False) -> Site:
    return Site(
        name=name,
        domain=domain,
        host="127.0.0.1",
        port=8888,
        health_path="/health/",
        tls=tls,
    )


def test_ensure_preserves_existing_logical_name(tmp_path, monkeypatch) -> None:
    config = tmp_path / "web.toml"
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(config))
    write_sites([_site("arthexis", "arthexis.com")])

    def _ensure(**kwargs):
        write_sites([_site(kwargs["fqdn"], kwargs["fqdn"], tls=True)])
        return {"success": True, "fqdn": kwargs["fqdn"]}

    monkeypatch.setattr(exposure_api.exposure, "ensure", _ensure)

    result = exposure_api.ensure(
        fqdn="arthexis.com",
        upstream="http://127.0.0.1:8888",
    )

    assert result["success"] is True
    configured = read_sites()
    assert len(configured) == 1
    assert configured[0].name == "arthexis"
    assert configured[0].domain == "arthexis.com"
    assert configured[0].tls is True


def test_ensure_uses_fqdn_name_for_new_domain(tmp_path, monkeypatch) -> None:
    config = tmp_path / "web.toml"
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(config))

    def _ensure(**kwargs):
        write_sites([_site(kwargs["fqdn"], kwargs["fqdn"], tls=True)])
        return {"success": True, "fqdn": kwargs["fqdn"]}

    monkeypatch.setattr(exposure_api.exposure, "ensure", _ensure)

    exposure_api.ensure(
        fqdn="repo.example.com",
        upstream="http://127.0.0.1:8050",
    )

    assert read_sites()[0].name == "repo.example.com"


def test_ensure_rejects_unrelated_fqdn_name_collision(tmp_path, monkeypatch) -> None:
    config = tmp_path / "web.toml"
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(config))
    write_sites(
        [
            _site("arthexis", "arthexis.com"),
            _site("arthexis.com", "admin.example.com"),
        ]
    )
    before = read_sites()
    called = False

    def _ensure(**kwargs):
        nonlocal called
        called = True
        return {"success": True, "fqdn": kwargs["fqdn"]}

    monkeypatch.setattr(exposure_api.exposure, "ensure", _ensure)

    with pytest.raises(ValueError, match="site name is already used"):
        exposure_api.ensure(
            fqdn="arthexis.com",
            upstream="http://127.0.0.1:8888",
        )

    assert called is False
    assert read_sites() == before


def test_failed_release_restores_logical_name(tmp_path, monkeypatch) -> None:
    config = tmp_path / "web.toml"
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(config))
    write_sites([_site("arthexis", "arthexis.com", tls=True)])

    def _release(**kwargs):
        configured = read_sites()
        assert configured[0].name == "arthexis.com"
        return {"fqdn": kwargs["fqdn"], "released": False, "stage": "nginx"}

    monkeypatch.setattr(exposure_api.exposure, "release", _release)

    result = exposure_api.release(fqdn="arthexis.com")

    assert result["released"] is False
    assert read_sites()[0].name == "arthexis"


def test_release_rejects_unrelated_fqdn_name_collision(tmp_path, monkeypatch) -> None:
    config = tmp_path / "web.toml"
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(config))
    write_sites(
        [
            _site("arthexis", "arthexis.com", tls=True),
            _site("arthexis.com", "admin.example.com", tls=True),
        ]
    )
    before = read_sites()
    called = False

    def _release(**kwargs):
        nonlocal called
        called = True
        return {"fqdn": kwargs["fqdn"], "released": True}

    monkeypatch.setattr(exposure_api.exposure, "release", _release)

    with pytest.raises(ValueError, match="site name is already used"):
        exposure_api.release(fqdn="arthexis.com")

    assert called is False
    assert read_sites() == before
