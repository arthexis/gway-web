"""Policy-aware MCP tool dispatch through the existing GWay Web API boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .api_config import APIConfig
from .api_dispatch import APIArgumentError, APINotFoundError, DispatcherLike, dispatch_api_request
from .api_routing import APIRequest
from .mcp_config import MCPConfig

_MAX_ARGUMENTS = 64
_MAX_RESULT_BYTES = 256 * 1024


class MCPToolError(RuntimeError):
    """Base transport-safe MCP tool failure."""


class MCPToolNotFoundError(MCPToolError):
    """Raised for unknown or denied MCP tools."""


class MCPToolArgumentError(MCPToolError):
    """Raised for malformed or invalid MCP tool arguments."""


class MCPToolExecutionError(MCPToolError):
    """Raised when an exposed tool fails without leaking internal details."""


@dataclass(frozen=True)
class MCPToolTarget:
    """Canonical project and command path represented by one MCP tool."""

    name: str
    project: str
    command_path: tuple[str, ...]


def targets_from_tools(tools: Sequence[Mapping[str, object]]) -> dict[str, MCPToolTarget]:
    """Build a collision-free tool-name lookup from generated schema metadata."""
    targets: dict[str, MCPToolTarget] = {}
    for tool in tools:
        name = tool.get("name")
        project = tool.get("project")
        command = tool.get("command")
        if not isinstance(name, str) or not isinstance(project, str):
            raise ValueError("invalid MCP tool metadata")
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise ValueError("invalid MCP tool command metadata")
        if name in targets:
            raise ValueError(f"duplicate MCP tool target: {name}")
        targets[name] = MCPToolTarget(name, project, tuple(command))
    return targets


def _argument_text(name: str, value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            raise MCPToolArgumentError(f"argument {name!r} must be finite")
        return str(value)
    if value is None:
        return ""
    raise MCPToolArgumentError(f"unsupported argument value for {name!r}")


def _arguments(values: Mapping[str, object] | None) -> dict[str, str]:
    if values is None:
        return {}
    if len(values) > _MAX_ARGUMENTS:
        raise MCPToolArgumentError(f"MCP tool calls support at most {_MAX_ARGUMENTS} arguments")
    result: dict[str, str] = {}
    for name, value in values.items():
        if not isinstance(name, str) or not name:
            raise MCPToolArgumentError("MCP argument names must be non-empty strings")
        result[name] = _argument_text(name, value)
    return result


def _bounded_result(value: object) -> object:
    try:
        payload = json.dumps(value, default=str, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise MCPToolExecutionError("tool returned an unsupported result") from exc
    if len(payload.encode("utf-8")) > _MAX_RESULT_BYTES:
        raise MCPToolExecutionError("tool result exceeds MCP response limit")
    return value


def dispatch_mcp_tool(
    dispatcher: DispatcherLike,
    api_policy: APIConfig,
    mcp_policy: MCPConfig,
    targets: Mapping[str, MCPToolTarget],
    tool_name: str,
    arguments: Mapping[str, object] | None = None,
) -> object:
    """Authorize and execute one MCP tool through the canonical API dispatcher."""
    target = targets.get(tool_name)
    if target is None or not mcp_policy.command_exposed(
        api_policy, target.project, target.command_path
    ):
        raise MCPToolNotFoundError("MCP tool is not exposed")

    request = APIRequest(
        project=target.project,
        command_path=target.command_path,
        arguments=_arguments(arguments),
    )
    try:
        result = dispatch_api_request(dispatcher, api_policy, request)
    except (APINotFoundError, KeyError):
        raise MCPToolNotFoundError("MCP tool is not exposed") from None
    except APIArgumentError as exc:
        raise MCPToolArgumentError(str(exc)) from None
    except MCPToolError:
        raise
    except Exception:
        raise MCPToolExecutionError("MCP tool execution failed") from None
    return _bounded_result(result)


__all__ = [
    "MCPToolArgumentError",
    "MCPToolError",
    "MCPToolExecutionError",
    "MCPToolNotFoundError",
    "MCPToolTarget",
    "dispatch_mcp_tool",
    "targets_from_tools",
]
