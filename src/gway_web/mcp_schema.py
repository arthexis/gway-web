"""Pure MCP tool-schema generation from GWay Web discovery metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .api_config import APIConfig
from .mcp_config import MCPConfig

_TOOL_PART = re.compile(r"[^A-Za-z0-9_]+")
_OPTIONAL_PREFIX = "Optional["
_SIMPLE_TYPES: dict[str, dict[str, object]] = {
    "str": {"type": "string"},
    "Path": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
}


class MCPUnsupportedSchemaError(ValueError):
    """Raised when discovery metadata cannot be represented safely as MCP input."""


def tool_name(canonical_project: str, command_path: Sequence[str]) -> str:
    """Return a deterministic MCP-safe tool identifier."""
    raw = "_".join((canonical_project, *command_path))
    normalized = _TOOL_PART.sub("_", raw).strip("_").lower()
    if not normalized:
        raise MCPUnsupportedSchemaError("MCP tool name resolves to an empty identifier")
    return normalized


def _base_type(type_name: object) -> tuple[str | None, bool]:
    if type_name is None:
        return None, False
    text = str(type_name).strip()
    if text.startswith(_OPTIONAL_PREFIX) and text.endswith("]"):
        return text[len(_OPTIONAL_PREFIX) : -1].strip(), True
    if "|" in text:
        parts = [part.strip() for part in text.split("|")]
        if len(parts) == 2 and "None" in parts:
            return next(part for part in parts if part != "None"), True
    return text, False


def _parameter_schema(parameter: Mapping[str, object]) -> dict[str, object]:
    name = parameter.get("name")
    if not isinstance(name, str) or not name:
        raise MCPUnsupportedSchemaError("MCP parameters require non-empty names")

    base, nullable = _base_type(parameter.get("type"))
    if base is None:
        schema: dict[str, object] = {"type": "string"}
    else:
        template = _SIMPLE_TYPES.get(base)
        if template is None:
            raise MCPUnsupportedSchemaError(
                f"unsupported MCP parameter type for {name!r}: {base}"
            )
        schema = dict(template)
    if nullable:
        schema = {"anyOf": [schema, {"type": "null"}]}

    description = parameter.get("description")
    if isinstance(description, str) and description:
        schema["description"] = description
    if "default" in parameter:
        schema["default"] = parameter["default"]
    return schema


def command_tool(
    canonical_project: str,
    command: Mapping[str, object],
) -> dict[str, object]:
    """Convert one discovered HTTP-visible command into a typed MCP tool definition."""
    path_value = command.get("path")
    if not isinstance(path_value, list) or not path_value or not all(
        isinstance(part, str) and part for part in path_value
    ):
        raise MCPUnsupportedSchemaError("MCP command path must be a non-empty string list")
    path = tuple(path_value)

    raw_parameters = command.get("parameters", [])
    if not isinstance(raw_parameters, list):
        raise MCPUnsupportedSchemaError("MCP command parameters must be a list")

    properties: dict[str, object] = {}
    required: list[str] = []
    for raw in raw_parameters:
        if not isinstance(raw, Mapping):
            raise MCPUnsupportedSchemaError("MCP parameter metadata must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise MCPUnsupportedSchemaError("MCP parameters require non-empty names")
        if name in properties:
            raise MCPUnsupportedSchemaError(f"duplicate MCP parameter name: {name}")
        properties[name] = _parameter_schema(raw)
        if raw.get("required") is True:
            required.append(name)

    input_schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        input_schema["required"] = required

    description = command.get("description") or command.get("summary")
    tool: dict[str, object] = {
        "name": tool_name(canonical_project, path),
        "inputSchema": input_schema,
        "project": canonical_project,
        "command": list(path),
    }
    if isinstance(description, str) and description:
        tool["description"] = description
    return tool


def tools_from_discovery(
    discovery: Mapping[str, object],
    *,
    api_policy: APIConfig,
    mcp_policy: MCPConfig,
) -> list[dict[str, object]]:
    """Return deterministic MCP tools passing both HTTP and MCP exposure policy."""
    project = discovery.get("project")
    commands = discovery.get("commands")
    if not isinstance(project, str) or not isinstance(commands, list):
        raise MCPUnsupportedSchemaError("invalid API discovery payload")

    tools: list[dict[str, object]] = []
    names: set[str] = set()
    for command in commands:
        if not isinstance(command, Mapping):
            raise MCPUnsupportedSchemaError("invalid discovered command metadata")
        path = command.get("path")
        if not isinstance(path, list) or not all(isinstance(part, str) for part in path):
            raise MCPUnsupportedSchemaError("invalid discovered command path")
        if not mcp_policy.command_exposed(api_policy, project, path):
            continue
        tool = command_tool(project, command)
        name = str(tool["name"])
        if name in names:
            raise MCPUnsupportedSchemaError(f"duplicate MCP tool name: {name}")
        names.add(name)
        tools.append(tool)

    tools.sort(key=lambda item: str(item["name"]))
    return tools


__all__ = [
    "MCPUnsupportedSchemaError",
    "command_tool",
    "tool_name",
    "tools_from_discovery",
]
