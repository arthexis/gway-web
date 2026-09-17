"""Managed Streamable HTTP service entry point for GWay Web MCP."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import uvicorn
from mcp.server import ServerRequestContext

from .api_config import APIConfig, read_api_config
from .api_service import _loopback_host
from .mcp_dispatch import MCPToolTarget
from .mcp_server import build_configured_mcp_server, streamable_http_app
from .tokens import verify_token

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8051


def _bearer_token(headers: Mapping[str, str] | None) -> str | None:
    if headers is None:
        return None
    authorization = headers.get("authorization") or headers.get("Authorization") or ""
    scheme, separator, credential = authorization.partition(" ")
    valid_shape = (
        bool(separator)
        and scheme.casefold() == "bearer"
        and bool(credential)
        and credential.strip() == credential
        and not any(character.isspace() for character in credential)
    )
    return credential if valid_shape else None


def bearer_authorizer(api_policy: APIConfig):
    """Authorize an MCP target with the existing project API bearer scope."""

    def authorize(
        context: ServerRequestContext[Any], target: MCPToolTarget | None
    ) -> bool:
        if target is None:
            return False
        scope = api_policy.project_scope(target.project)
        if scope is None:
            return False
        request = context.request
        headers = getattr(request, "headers", None) if request is not None else None
        token = _bearer_token(headers)
        return token is not None and verify_token(token, scope=scope)

    return authorize


def main() -> None:
    from gway.dispatcher import Dispatcher

    host = _loopback_host(os.environ.get("GWAY_WEB_MCP_HOST", DEFAULT_HOST))
    port = int(os.environ.get("GWAY_WEB_MCP_PORT", str(DEFAULT_PORT)))
    api_policy = read_api_config()
    server = build_configured_mcp_server(
        Dispatcher(),
        api_policy=api_policy,
        authorizer=bearer_authorizer(api_policy),
    )
    app = streamable_http_app(server, host=host)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover - module service entry point
    main()
