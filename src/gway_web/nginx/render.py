"""Pure Nginx configuration rendering from portable Site intent."""

from __future__ import annotations

from pathlib import Path

from ..site import Site

DEFAULT_ACME_WEBROOT = Path("/var/www/gway-acme")


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

    if acme_webroot is not None:
        webroot = str(acme_webroot)
        _validate_path(webroot)
        lines.extend(
            [
                "",
                "    location ^~ /.well-known/acme-challenge/ {",
                f"        root {webroot};",
                "        try_files $uri =404;",
                "    }",
            ]
        )

    lines.extend(
        [
            "",
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
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_nginx_token(value: str, *, field: str) -> None:
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"{field} is not safe for Nginx configuration")
    if any(character in value for character in ";{}"):
        raise ValueError(f"{field} is not safe for Nginx configuration")


def _validate_path(value: str) -> None:
    if not value or "\n" in value or "\r" in value or ";" in value:
        raise ValueError("ACME webroot is not safe for Nginx configuration")
