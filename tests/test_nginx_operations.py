from pathlib import Path

import pytest

from gway_web.nginx import NginxLayout, disable, enable, expose, reload as reload_nginx
from gway_web.site import Site


def _layout(tmp_path: Path) -> NginxLayout:
    root = tmp_path / "nginx"
    (root / "sites-available").mkdir(parents=True)
    (root / "sites-enabled").mkdir()
    (root / "nginx.conf").write_text("events {}\n", encoding="utf-8")
    return NginxLayout(
        executable=tmp_path / "bin" / "nginx",
        config_root=root,
        nginx_conf=root / "nginx.conf",
        sites_available=root / "sites-available",
        sites_enabled=root / "sites-enabled",
        conf_d=root / "conf.d",
    )


def test_expose_activates_generated_site_after_validation(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    calls = []
    monkeypatch.setattr("gway_web.nginx.operations.test", lambda current: calls.append("test"))
    monkeypatch.setattr("gway_web.nginx.operations._reload", lambda current: calls.append("reload"))

    target = expose(Site(name="arthexis", domain="charge.example.com"), layout=layout)

    assert target.name == "gway-arthexis.conf"
    assert "server_name charge.example.com;" in target.read_text(encoding="utf-8")
    assert (layout.sites_enabled / target.name).resolve() == target.resolve()
    assert calls == ["test", "reload"]


def test_expose_restores_working_file_and_link_when_validation_fails(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    target = layout.sites_available / "gway-arthexis.conf"
    target.write_text("old config\n", encoding="utf-8")
    old_target = layout.sites_available / "old.conf"
    old_target.write_text("old enabled\n", encoding="utf-8")
    enabled = layout.sites_enabled / target.name
    enabled.symlink_to(old_target)
    calls = []

    def fail_once(_layout):
        calls.append("test")
        if len(calls) == 1:
            raise RuntimeError("invalid nginx")

    monkeypatch.setattr("gway_web.nginx.operations.test", fail_once)
    monkeypatch.setattr("gway_web.nginx.operations._reload", lambda current: calls.append("reload"))

    with pytest.raises(RuntimeError, match="invalid nginx"):
        expose(Site(name="arthexis", domain="new.example.com"), layout=layout)

    assert target.read_text(encoding="utf-8") == "old config\n"
    assert enabled.readlink() == old_target
    assert calls == ["test", "test", "reload"]


def test_expose_restores_working_state_when_reload_fails(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    target = layout.sites_available / "gway-arthexis.conf"
    target.write_text("old config\n", encoding="utf-8")
    enabled = layout.sites_enabled / target.name
    enabled.write_text("old enabled file\n", encoding="utf-8")
    reload_calls = []

    monkeypatch.setattr("gway_web.nginx.operations.test", lambda current: None)

    def fail_once(_layout):
        reload_calls.append("reload")
        if len(reload_calls) == 1:
            raise RuntimeError("reload failed")

    monkeypatch.setattr("gway_web.nginx.operations._reload", fail_once)

    with pytest.raises(RuntimeError, match="reload failed"):
        expose(Site(name="arthexis", domain="new.example.com"), layout=layout)

    assert target.read_text(encoding="utf-8") == "old config\n"
    assert not enabled.is_symlink()
    assert enabled.read_text(encoding="utf-8") == "old enabled file\n"
    assert reload_calls == ["reload", "reload"]


def test_enable_and_disable_are_transactional(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    site = Site(name="arthexis")
    target = layout.sites_available / "gway-arthexis.conf"
    target.write_text("server {}\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr("gway_web.nginx.operations.test", lambda current: calls.append("test"))
    monkeypatch.setattr("gway_web.nginx.operations._reload", lambda current: calls.append("reload"))

    enabled = enable(site, layout=layout)
    assert enabled.is_symlink()
    disable(site, layout=layout)
    assert not enabled.exists()
    assert calls == ["test", "reload", "test", "reload"]


def test_reload_validates_only_once(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    calls = []
    monkeypatch.setattr("gway_web.nginx.operations.test", lambda current: calls.append("test"))
    monkeypatch.setattr("gway_web.nginx.operations._reload", lambda current: calls.append("reload"))

    reload_nginx(layout)

    assert calls == ["test", "reload"]


def test_expose_rejects_unsafe_site_filename(tmp_path):
    layout = _layout(tmp_path)
    with pytest.raises(ValueError, match="site name is not safe"):
        expose(Site(name="../escape"), layout=layout)


def test_expose_attaches_existing_tls_certificate(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    certificate = tmp_path / "fullchain.pem"
    key = tmp_path / "privkey.pem"
    certificate.write_text("certificate\n", encoding="utf-8")
    key.write_text("key\n", encoding="utf-8")
    monkeypatch.setattr("gway_web.nginx.operations.test", lambda current: None)
    monkeypatch.setattr("gway_web.nginx.operations._reload", lambda current: None)

    target = expose(
        Site(
            name="arthexis",
            domain="charge.example.com",
            tls=True,
            tls_certificate=certificate,
            tls_certificate_key=key,
        ),
        layout=layout,
    )

    rendered = target.read_text(encoding="utf-8")
    assert "listen 443 ssl;" in rendered
    assert f"ssl_certificate {certificate};" in rendered
    assert f"ssl_certificate_key {key};" in rendered


def test_expose_rejects_missing_tls_certificate_before_mutation(tmp_path):
    layout = _layout(tmp_path)
    target = layout.sites_available / "gway-arthexis.conf"

    with pytest.raises(FileNotFoundError, match="TLS certificate does not exist"):
        expose(
            Site(
                name="arthexis",
                domain="charge.example.com",
                tls=True,
                tls_certificate=tmp_path / "missing.pem",
                tls_certificate_key=tmp_path / "missing-key.pem",
            ),
            layout=layout,
        )

    assert not target.exists()
    assert not (layout.sites_enabled / target.name).exists()
