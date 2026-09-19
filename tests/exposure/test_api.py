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


@pytest.fixture(autouse=True)
def _isolated_site_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GWAY_WEB_CONFIG", str(tmp_path / "web.toml"))


def _fake_ensure(**kwargs):
    write_sites([_site(kwargs["fqdn"], kwargs["fqdn"], tls=True)])
    return {"success": True, "fqdn": kwargs["fqdn"]}


def test_ensure_preserves_existing_logical_name(monkeypatch) -> None:
    write_sites([_site("arthexis", "arthexis.com")])
    monkeypatch.setattr(exposure_api.exposure, "ensure", _fake_ensure)

    result = exposure_api.ensure(
        fqdn="arthexis.com",
        upstream="http://127.0.0.1:8888",
    )

    assert result["success"] is True
    configured = read_sites()
    assert configured == [_site("arthexis", "arthexis.com", tls=True)]


def test_ensure_uses_fqdn_name_for_new_domain(monkeypatch) -> None:
    monkeypatch.setattr(exposure_api.exposure, "ensure", _fake_ensure)

    exposure_api.ensure(
        fqdn="repo.example.com",
        upstream="http://127.0.0.1:8050",
    )

    assert read_sites()[0].name == "repo.example.com"


@pytest.mark.parametrize(
    ("configured", "fqdn", "upstream"),
    [
        (
            [
                _site("arthexis", "arthexis.com"),
                _site("arthexis.com", "admin.example.com"),
            ],
            "arthexis.com",
            "http://127.0.0.1:8888",
        ),
        (
            [_site("repo.example.com", "admin.example.com")],
            "repo.example.com",
            "http://127.0.0.1:8050",
        ),
    ],
)
def test_ensure_rejects_site_name_collisions(
    configured,
    fqdn: str,
    upstream: str,
    monkeypatch,
) -> None:
    write_sites(configured)
    before = read_sites()
    called = False

    def fake_ensure(**kwargs):
        nonlocal called
        called = True
        return {"success": True, "fqdn": kwargs["fqdn"]}

    monkeypatch.setattr(exposure_api.exposure, "ensure", fake_ensure)

    with pytest.raises(ValueError, match="site name is already used"):
        exposure_api.ensure(fqdn=fqdn, upstream=upstream)

    assert called is False
    assert read_sites() == before


def test_failed_release_restores_logical_name(monkeypatch) -> None:
    write_sites([_site("arthexis", "arthexis.com", tls=True)])

    def fake_release(**kwargs):
        assert read_sites()[0].name == "arthexis.com"
        return {"fqdn": kwargs["fqdn"], "released": False, "stage": "nginx"}

    monkeypatch.setattr(exposure_api.exposure, "release", fake_release)

    result = exposure_api.release(fqdn="arthexis.com")

    assert result["released"] is False
    assert read_sites()[0].name == "arthexis"


def test_release_rejects_unrelated_fqdn_name_collision(monkeypatch) -> None:
    write_sites(
        [
            _site("arthexis", "arthexis.com", tls=True),
            _site("arthexis.com", "admin.example.com", tls=True),
        ]
    )
    before = read_sites()
    called = False

    def fake_release(**kwargs):
        nonlocal called
        called = True
        return {"fqdn": kwargs["fqdn"], "released": True}

    monkeypatch.setattr(exposure_api.exposure, "release", fake_release)

    with pytest.raises(ValueError, match="site name is already used"):
        exposure_api.release(fqdn="arthexis.com")

    assert called is False
    assert read_sites() == before
