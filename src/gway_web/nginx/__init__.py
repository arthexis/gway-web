"""Internal Nginx backend primitives for gway-web."""

from .discovery import NginxLayout, discover_nginx
from .operations import NginxSiteSnapshot, disable, enable, expose, reload, restore, snapshot, test
from .render import render_http_proxy, render_proxy

__all__ = [
    "NginxLayout",
    "NginxSiteSnapshot",
    "disable",
    "discover_nginx",
    "enable",
    "expose",
    "reload",
    "render_http_proxy",
    "render_proxy",
    "restore",
    "snapshot",
    "test",
]
