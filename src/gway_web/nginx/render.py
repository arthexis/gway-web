"""Pure Nginx configuration rendering from portable Site intent."""

from __future__ import annotations

from pathlib import Path

from ..site import Site
from ..tls import certificate_paths

DEFAULT_ACME_WEBROOT = Path("/var/www/gway-acme")


def render_proxy(
    site: Site,
    *,
    acme_webroot: str | Path | None = DEFAULT_ACME_WEBROOT,
) -> str:
    """Render the complete reverse-proxy configuration for a site."""

    if not site.tls:
        return render_http_proxy(site, acme_webroot=acme_webroot)

    certificate, key = certificate_paths(site)
    _validate_nginx_token(site.domain or "_", field="domain")
    _validate_nginx_token(site.host, field="host")
    _validate_path(str(certificate), field="TLS certificate")
    _validate_path(str(key), field="TLS certificate key")

    if site.redirect_http:
        http = _render_http_redirect(site, acme_webroot=acme_webroot)
    else:
        http = render_http_proxy(site, acme_webroot=acme_webroot)
    return http + _render_https_proxy(site, certificate=certificate, key=key)


def render_http_proxy(
    site: Site,
    *,
    acme_webroot: str | Path | None = DEFAULT_ACME_WEBROOT,
) -> str:
    """Render an HTTP reverse-proxy server block without touching the host."""

    server_name = site.domain or "_"
    _validate_nginx_token(server_name, field="domain")
    _validate_nginx_token(site.host, field="host")

    lines = [
        "server {",
        "    listen 80;",
        f"    server_name {server_name};",
    ]
    _append_acme_location(lines, acme_webroot)
    lines.extend(["", *_proxy_location(site), "}", ""])
    return "\n".join(lines)


def _render_http_redirect(
    site: Site,
    *,
    acme_webroot: str | Path | None,
) -> str:
    server_name = site.domain or "_"
    lines = [
        "server {",
        "    listen 80;",
        f"    server_name {server_name};",
    ]
    _append_acme_location(lines, acme_webroot)
    lines.extend(
        [
            "",
            "    location / {",
            "        return 301 https://$host$request_uri;",
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _render_https_proxy(site: Site, *, certificate: Path, key: Path) -> str:
    server_name = site.domain or "_"
    lines = [
        "server {",
        "    listen 443 ssl;",
        f"    server_name {server_name};",
        f"    ssl_certificate {certificate};",
        f"    ssl_certificate_key {key};",
        "",
        *_proxy_location(site),
        "}",
        "",
    ]
    return "\n".join(lines)


def _append_acme_location(lines: list[str], acme_webroot: str | Path | None) -> None:
    if acme_webroot is None:
        return
    webroot = str(acme_webroot)
    _validate_path(webroot, field="ACME webroot")
    lines.extend(
        [
            "",
            "    location ^~ /.well-known/acme-challenge/ {",
            f"        root {webroot};",
            "        try_files $uri =404;",
            "    }",
        ]
    )


def _proxy_location(site: Site) -> list[str]:
    return [
        "    location / {",
        f"        proxy_pass {site.upstream_url};",
        "        proxy_http_version 1.1;",
        "        proxy_set_header Host $host;",
        "        proxy_set_header X-Real-IP $remote_addr;",
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        "        proxy_set_header Upgrade $http_upgrade;",
        '        proxy_set_header Connection "upgrade";',
        "    }",
    ]


def _validate_nginx_token(value: str, *, field: str) -> None:
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"{field} is not safe for Nginx configuration")
    if any(character in value for character in ";{}"):
        raise ValueError(f"{field} is not safe for Nginx configuration")


def _validate_path(value: str, *, field: str) -> None:
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"{field} is not safe for Nginx configuration")
    if any(character in value for character in ";{}"):
        raise ValueError(f"{field} is not safe for Nginx configuration")
