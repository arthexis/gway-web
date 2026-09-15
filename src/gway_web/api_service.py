"""Managed service entry point for the authenticated single-call GWay API."""

from __future__ import annotations

import ipaddress
import os
import socket

from .api_config import read_api_config
from .api_http import DEFAULT_MAX_RESPONSE_BYTES, serve_api

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8050


def _loopback_host(value: str) -> str:
    """Return a validated loopback bind target for the managed API service."""
    host = value.strip()
    if not host:
        raise ValueError("GWAY_WEB_API_HOST must use a loopback address")
    if host.casefold() == "localhost":
        return host
    try:
        if ipaddress.ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise ValueError("GWAY_WEB_API_HOST must use a loopback address") from exc
    if addresses and all(ipaddress.ip_address(address).is_loopback for address in addresses):
        return host
    raise ValueError("GWAY_WEB_API_HOST must use a loopback address")


def main() -> None:
    from gway.dispatcher import Dispatcher

    host = _loopback_host(os.environ.get("GWAY_WEB_API_HOST", DEFAULT_HOST))
    port = int(os.environ.get("GWAY_WEB_API_PORT", str(DEFAULT_PORT)))
    max_response_bytes = int(
        os.environ.get("GWAY_WEB_API_MAX_RESPONSE_BYTES", str(DEFAULT_MAX_RESPONSE_BYTES))
    )
    serve_api(
        Dispatcher(),
        read_api_config(),
        host=host,
        port=port,
        max_response_bytes=max_response_bytes,
    )


if __name__ == "__main__":  # pragma: no cover - module service entry point
    main()
