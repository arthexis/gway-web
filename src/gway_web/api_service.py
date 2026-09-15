"""Managed service entry point for the authenticated single-call GWay API."""

from __future__ import annotations

import os

from gway.dispatcher import Dispatcher

from .api_config import read_api_config
from .api_http import DEFAULT_MAX_RESPONSE_BYTES, serve_api

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8050


def main() -> None:
    host = os.environ.get("GWAY_WEB_API_HOST", DEFAULT_HOST)
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
