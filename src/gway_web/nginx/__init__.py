"""Internal Nginx backend primitives for gway-web."""

from .discovery import NginxLayout, discover_nginx
from .operations import disable, enable, expose, reload, test
from .render import render_http_proxy, render_proxy

__all__ = [
    "NginxLayout",
    "disable",
    "discover_nginx",
    "enable",
    "expose",
    "reload",
    "render_http_proxy",
    "render_proxy",
    "test",
]
