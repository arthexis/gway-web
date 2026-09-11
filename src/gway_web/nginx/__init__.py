"""Internal Nginx backend primitives for gway-web."""

from .discovery import NginxLayout, discover_nginx
from .render import render_http_proxy

__all__ = ["NginxLayout", "discover_nginx", "render_http_proxy"]
