from pathlib import Path

import pytest

from gway_web.nginx import NginxLayout, discover_nginx, render_http_proxy, render_proxy
from gway_web.site import Site
from gway_web.tls import certificate_paths


def test_discover_nginx_with_explicit_synthetic_layout(tmp_path: Path):
    root = tmp_path / "nginx"
    layout = discover_nginx(executable=tmp_path / "bin" / "nginx", config_root=root)

    assert layout == NginxLayout(
        executable=tmp_path / "bin" / "nginx",
        config_root=root,
        nginx_conf=root / "nginx.conf",
        sites_available=root / "sites-available",
        sites_enabled=root / "sites-enabled",
        conf_d=root / "conf.d",
    )


def test_render_http_proxy_is_deterministic():
    site = Site(
        name="arthexis",
        domain="charge.example.com",
        host="127.0.0.1",
        port=8888,
        health_path="/health/",
    )

    assert (
        render_http_proxy(site)
        == """server {
    listen 80;
    server_name charge.example.com;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/gway-acme;
        try_files $uri =404;
    }

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
"""
    )


def test_render_http_proxy_can_omit_acme_location():
    rendered = render_http_proxy(Site(name="local"), acme_webroot=None)

    assert ".well-known/acme-challenge" not in rendered
    assert "server_name _;" in rendered


def test_render_http_proxy_rejects_nginx_directive_injection():
    with pytest.raises(ValueError, match="domain is not safe"):
        render_http_proxy(Site(name="bad", domain="example.com; return 444"))


def test_tls_uses_conventional_letsencrypt_paths():
    certificate, key = certificate_paths(
        Site(name="arthexis", domain="charge.example.com", tls=True)
    )

    assert certificate == Path("/etc/letsencrypt/live/charge.example.com/fullchain.pem")
    assert key == Path("/etc/letsencrypt/live/charge.example.com/privkey.pem")


def test_render_tls_proxy_with_attached_certificate(tmp_path: Path):
    certificate = tmp_path / "fullchain.pem"
    key = tmp_path / "privkey.pem"
    site = Site(
        name="arthexis",
        domain="charge.example.com",
        host="127.0.0.1",
        port=8888,
        tls=True,
        tls_certificate=certificate,
        tls_certificate_key=key,
    )

    rendered = render_proxy(site)

    assert "listen 80;" in rendered
    assert "return 301 https://$host$request_uri;" in rendered
    assert "listen 443 ssl;" in rendered
    assert f"ssl_certificate {certificate};" in rendered
    assert f"ssl_certificate_key {key};" in rendered
    assert "proxy_pass http://127.0.0.1:8888;" in rendered


def test_tls_can_keep_http_proxying_without_redirect(tmp_path: Path):
    site = Site(
        name="arthexis",
        domain="charge.example.com",
        tls=True,
        redirect_http=False,
        tls_certificate=tmp_path / "fullchain.pem",
        tls_certificate_key=tmp_path / "privkey.pem",
    )

    rendered = render_proxy(site)

    assert "return 301" not in rendered
    assert rendered.count("proxy_pass http://127.0.0.1:8000;") == 2
