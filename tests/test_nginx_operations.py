from pathlib import Path

import pytest

from gway_web.nginx import NginxLayout, disable, enable, expose
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
    monkeypatch.setattr("gway_web.nginx.operations.reload", lambda current: calls.append("reload"))

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

    def fail(_layout):
        raise RuntimeError("invalid nginx")

    monkeypatch.setattr("gway_web.nginx.operations.test", fail)

    with pytest.raises(RuntimeError, match="invalid nginx"):
        expose(Site(name="arthexis", domain="new.example.com"), layout=layout)

    assert target.read_text(encoding="utf-8") == "old config\n"
    assert enabled.readlink() == old_target


def test_enable_and_disable_are_transactional(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    site = Site(name="arthexis")
    target = layout.sites_available / "gway-arthexis.conf"
    target.write_text("server {}\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr("gway_web.nginx.operations.test", lambda current: calls.append("test"))
    monkeypatch.setattr("gway_web.nginx.operations.reload", lambda current: calls.append("reload"))

    enabled = enable(site, layout=layout)
    assert enabled.is_symlink()
    disable(site, layout=layout)
    assert not enabled.exists()
    assert calls == ["test", "reload", "test", "reload"]


def test_expose_rejects_unsafe_site_filename(tmp_path):
    layout = _layout(tmp_path)
    with pytest.raises(ValueError, match="site name is not safe"):
        expose(Site(name="../escape"), layout=layout)
