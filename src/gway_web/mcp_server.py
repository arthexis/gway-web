"""Thin MCP protocol adapter over generated GWay Web tool metadata."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from .api_config import APIConfig, read_api_config
from .api_discovery import DiscoveryDispatcherLike, discover_project
from .api_dispatch import DispatcherLike
from .mcp_config import MCPConfig, read_mcp_config
from .mcp_dispatch import (
    MAX_MCP_RESPONSE_BYTES,
    MCPToolArgumentError,
    MCPToolError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
    MCPToolTarget,
    dispatch_mcp_tool,
    targets_from_tools,
)
from .mcp_schema import tools_from_discovery

Authorizer = Callable[[ServerRequestContext[Any], MCPToolTarget | None], bool | Awaitable[bool]]
_JSON_RPC_ENVELOPE_RESERVE = 1024


async def _authorized(
    authorizer: Authorizer | None,
    context: ServerRequestContext[Any],
    target: MCPToolTarget | None,
) -> bool:
    if authorizer is None:
        return False
    allowed = authorizer(context, target)
    if inspect.isawaitable(allowed):
        allowed = await allowed
    return allowed is True


def _protocol_tools(tools: Sequence[Mapping[str, object]]) -> list[Tool]:
    result: list[Tool] = []
    for tool in tools:
        name = tool.get("name")
        schema = tool.get("inputSchema")
        description = tool.get("description")
        if not isinstance(name, str) or not isinstance(schema, dict):
            raise ValueError("invalid generated MCP tool metadata")
        result.append(
            Tool(
                name=name,
                description=description if isinstance(description, str) else None,
                input_schema=schema,
            )
        )
    return result


def _result(value: object) -> CallToolResult:
    """Build one bounded MCP result, accounting for both wire representations."""
    text = json.dumps(value, default=str, allow_nan=False, ensure_ascii=False)
    structured = value if isinstance(value, dict) else {"result": value}
    result = CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=structured,
    )
    wire = json.dumps(
        result.model_dump(by_alias=True, mode="json", exclude_none=True),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(wire) + _JSON_RPC_ENVELOPE_RESERVE > MAX_MCP_RESPONSE_BYTES:
        raise MCPToolExecutionError("tool result exceeds MCP response limit")
    return result


def _error(error: MCPToolError) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=str(error))],
        is_error=True,
    )


def build_mcp_server(
    dispatcher: DispatcherLike,
    api_policy: APIConfig,
    mcp_policy: MCPConfig,
    tools: Sequence[Mapping[str, object]],
    *,
    authorizer: Authorizer | None = None,
    name: str = "gway-web",
    version: str = "0.1.0",
) -> Server[Any]:
    """Build a read-only low-level MCP server from prevalidated tool metadata.

    An authorizer is required for tools to be visible or callable. Tool listing
    is filtered target-by-target so credentials for one project never reveal
    another project's MCP schema.
    """
    protocol_tools = _protocol_tools(tools)
    targets = targets_from_tools(tools)

    async def list_tools(
        context: ServerRequestContext[Any],
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        del params
        visible: list[Tool] = []
        for tool in protocol_tools:
            target = targets.get(tool.name)
            if target is not None and await _authorized(authorizer, context, target):
                visible.append(tool)
        return ListToolsResult(tools=visible)

    async def call_tool(
        context: ServerRequestContext[Any],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        target = targets.get(params.name)
        if target is None or not await _authorized(authorizer, context, target):
            return _error(MCPToolNotFoundError("MCP tool is not exposed"))
        try:
            value = dispatch_mcp_tool(
                dispatcher,
                api_policy,
                mcp_policy,
                targets,
                params.name,
                params.arguments or {},
            )
            return _result(value)
        except (MCPToolNotFoundError, MCPToolArgumentError, MCPToolExecutionError) as exc:
            return _error(exc)

    return Server(
        name,
        version=version,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def build_configured_mcp_server(
    dispatcher: DiscoveryDispatcherLike,
    *,
    api_policy: APIConfig | None = None,
    mcp_policy: MCPConfig | None = None,
    authorizer: Authorizer | None = None,
    name: str = "gway-web",
    version: str = "0.1.0",
) -> Server[Any]:
    """Load persisted policy and build the deployable MCP server.

    Explicit policy objects remain injectable for tests and embedded callers.
    When omitted, startup reads the normal dedicated API and MCP policy files.
    Missing policy files retain each layer's deny-by-default behavior.
    """
    selected_api = read_api_config() if api_policy is None else api_policy
    selected_mcp = read_mcp_config() if mcp_policy is None else mcp_policy

    tools: list[dict[str, object]] = []
    names: set[str] = set()
    for project in selected_mcp.projects:
        discovery = discover_project(dispatcher, selected_api, project.name)
        for tool in tools_from_discovery(
            discovery,
            api_policy=selected_api,
            mcp_policy=selected_mcp,
        ):
            tool_name = str(tool["name"])
            if tool_name in names:
                raise ValueError(f"duplicate MCP tool name: {tool_name}")
            names.add(tool_name)
            tools.append(tool)
    tools.sort(key=lambda item: str(item["name"]))

    return build_mcp_server(
        dispatcher,
        selected_api,
        selected_mcp,
        tools,
        authorizer=authorizer,
        name=name,
        version=version,
    )


def streamable_http_app(
    server: Server[Any],
    *,
    host: str = "127.0.0.1",
    allowed_hosts: Sequence[str] = (),
    json_response: bool = True,
    stateless_http: bool = True,
):
    """Build the SDK Streamable HTTP ASGI app with explicit Host protection."""
    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    for value in allowed_hosts:
        selected = value.strip().lower().rstrip(".")
        if not selected:
            continue
        hosts.extend([selected, f"{selected}:*"])
    security = TransportSecuritySettings(allowed_hosts=list(dict.fromkeys(hosts)))
    return server.streamable_http_app(
        host=host,
        json_response=json_response,
        stateless_http=stateless_http,
        transport_security=security,
    )


__all__ = [
    "Authorizer",
    "build_configured_mcp_server",
    "build_mcp_server",
    "streamable_http_app",
]
