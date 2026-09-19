from __future__ import annotations

import pytest

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.mcp_config import MCPConfig, MCPProjectExposure
from gway_web.mcp_schema import MCPUnsupportedSchemaError, tool_name, tools_from_discovery


def _api_policy(*functions: tuple[str, ...]) -> APIConfig:
    return APIConfig(
        projects=(
            APIProjectExposure("repo", frozenset(functions)),
        )
    )


def _mcp_policy(*functions: tuple[str, ...]) -> MCPConfig:
    return MCPConfig(
        projects=(
            MCPProjectExposure("repo", frozenset(functions)),
        )
    )


def _discovery() -> dict[str, object]:
    return {
        "project": "repo",
        "commands": [
            {
                "path": ["context"],
                "summary": "Read repository context",
                "parameters": [
                    {
                        "name": "path",
                        "required": True,
                        "positional": True,
                        "type": "str",
                        "description": "Repository-relative path",
                    },
                    {
                        "name": "depth",
                        "required": False,
                        "positional": False,
                        "type": "int",
                        "default": 2,
                    },
                    {
                        "name": "include_tests",
                        "required": False,
                        "positional": False,
                        "type": "bool",
                        "default": False,
                    },
                ],
            },
            {
                "path": ["impact"],
                "summary": "Analyze impact",
                "parameters": [],
            },
        ],
    }


def test_mcp_policy_cannot_widen_http_exposure() -> None:
    api = _api_policy(("context",))
    mcp = _mcp_policy(("context",), ("impact",))

    assert mcp.command_exposed(api, "repo", ("context",)) is True
    assert mcp.command_exposed(api, "repo", ("impact",)) is False
    assert mcp.exposed_commands(api, "repo") == (("context",),)


def test_tools_from_discovery_are_typed_deterministic_and_read_only_metadata() -> None:
    tools = tools_from_discovery(
        _discovery(),
        api_policy=_api_policy(("context",), ("impact",)),
        mcp_policy=_mcp_policy(("impact",), ("context",)),
    )

    assert [tool["name"] for tool in tools] == ["repo_context", "repo_impact"]
    context = tools[0]
    assert context["project"] == "repo"
    assert context["command"] == ["context"]
    assert context["description"] == "Read repository context"
    assert context["inputSchema"] == {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repository-relative path",
            },
            "depth": {"type": "integer", "default": 2},
            "include_tests": {"type": "boolean", "default": False},
        },
        "additionalProperties": False,
        "required": ["path"],
    }


def test_mcp_schema_supports_path_and_simple_optional_types() -> None:
    discovery = {
        "project": "repo",
        "commands": [
            {
                "path": ["read"],
                "parameters": [
                    {"name": "path", "required": True, "type": "Path"},
                    {"name": "cursor", "required": False, "type": "int | None"},
                ],
            }
        ],
    }

    tools = tools_from_discovery(
        discovery,
        api_policy=_api_policy(("read",)),
        mcp_policy=_mcp_policy(("read",)),
    )

    properties = tools[0]["inputSchema"]["properties"]
    assert properties["path"] == {"type": "string"}
    assert properties["cursor"] == {
        "anyOf": [{"type": "integer"}, {"type": "null"}]
    }


def test_unsupported_parameter_type_is_rejected() -> None:
    discovery = {
        "project": "repo",
        "commands": [
            {
                "path": ["unsafe"],
                "parameters": [
                    {"name": "payload", "required": True, "type": "dict[str, object]"}
                ],
            }
        ],
    }

    with pytest.raises(MCPUnsupportedSchemaError, match="unsupported MCP parameter type"):
        tools_from_discovery(
            discovery,
            api_policy=_api_policy(("unsafe",)),
            mcp_policy=_mcp_policy(("unsafe",)),
        )


def test_normalized_tool_name_collisions_are_rejected() -> None:
    discovery = {
        "project": "repo",
        "commands": [
            {"path": ["read-file"], "parameters": []},
            {"path": ["read_file"], "parameters": []},
        ],
    }
    api = _api_policy(("read-file",), ("read_file",))
    mcp = _mcp_policy(("read-file",), ("read_file",))

    with pytest.raises(MCPUnsupportedSchemaError, match="duplicate MCP tool name"):
        tools_from_discovery(discovery, api_policy=api, mcp_policy=mcp)


def test_tool_name_normalizes_project_and_command_path() -> None:
    assert tool_name("Repo Tools", ("Read/File",)) == "repo_tools_read_file"
