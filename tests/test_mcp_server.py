from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mcp import Client

from gway_web.api_config import APIConfig, APIProjectExposure, write_api_config
from gway_web.mcp_config import MCPConfig, MCPProjectExposure, write_mcp_config
from gway_web.mcp_schema import tools_from_discovery
from gway_web.mcp_server import (
    build_configured_mcp_server,
    build_mcp_server,
    streamable_http_app,
)


@dataclass
class _Project:
    name: str


@dataclass
class _Parameter:
    name: str
    required: bool = False
    positional: bool = False
    annotation: object | None = None
    default: object = None
    help: str | None = None
    negative_options: tuple[str, ...] | None = None


@dataclass
class _Command:
    path: tuple[str, ...]
    summary: str | None = None
    description: str | None = None
    parameters: tuple[_Parameter, ...] = ()


class _Registry:
    def require(self, token: str) -> _Project:
        if token == "repo":
            return _Project("repo")
        raise ValueError("unknown project")


class _Dispatcher:
    def __init__(self) -> None:
        self.registry = _Registry()
        self.calls = []

    def commands(self, project_name: str) -> tuple[_Command, ...]:
        assert project_name == "repo"
        return (
            _Command(
                ("context",),
                summary="Read context",
                parameters=(
                    _Parameter("query", required=True, annotation=str),
                ),
            ),
        )

    def invoke(self, project_name, command_path, arguments=None):
        self.calls.append((project_name, command_path, dict(arguments or {})))
        return {"query": arguments.get("query"), "count": 1}


def _policies():
    api = APIConfig(
        projects=(APIProjectExposure("repo", frozenset({("context",)})),)
    )
    mcp = MCPConfig(
        projects=(MCPProjectExposure("repo", frozenset({("context",)})),)
    )
    return api, mcp


def _tools(api, mcp):
    return tools_from_discovery(
        {
            "project": "repo",
            "commands": [
                {
                    "path": ["context"],
                    "summary": "Read context",
                    "parameters": [
                        {"name": "query", "required": True, "type": "str"}
                    ],
                }
            ],
        },
        api_policy=api,
        mcp_policy=mcp,
    )


def test_mcp_server_lists_and_calls_authorized_tools_in_process() -> None:
    async def exercise() -> None:
        dispatcher = _Dispatcher()
        api, mcp = _policies()
        server = build_mcp_server(
            dispatcher,
            api,
            mcp,
            _tools(api, mcp),
            authorizer=lambda context, target: True,
        )

        async with Client(server) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == ["repo_context"]

            result = await client.call_tool("repo_context", {"query": "battery"})
            assert result.is_error is False
            assert result.structured_content == {"query": "battery", "count": 1}

        assert dispatcher.calls == [
            ("repo", ("context",), {"query": "battery"})
        ]

    asyncio.run(exercise())


def test_mcp_server_filters_tool_listing_per_target_authorization() -> None:
    async def exercise() -> None:
        dispatcher = _Dispatcher()
        api = APIConfig(
            projects=(
                APIProjectExposure("repo", frozenset({("context",)})),
                APIProjectExposure("web", frozenset({("list-runs",)})),
            )
        )
        mcp = MCPConfig(
            projects=(
                MCPProjectExposure("repo", frozenset({("context",)})),
                MCPProjectExposure("web", frozenset({("list-runs",)})),
            )
        )
        tools = [
            {
                "name": "repo_context",
                "project": "repo",
                "command": ["context"],
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "web_list_runs",
                "project": "web",
                "command": ["list-runs"],
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
        server = build_mcp_server(
            dispatcher,
            api,
            mcp,
            tools,
            authorizer=lambda context, target: target is not None and target.project == "repo",
        )

        async with Client(server) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == ["repo_context"]

    asyncio.run(exercise())


def test_mcp_server_is_closed_without_authorizer() -> None:
    async def exercise() -> None:
        dispatcher = _Dispatcher()
        api, mcp = _policies()
        server = build_mcp_server(dispatcher, api, mcp, _tools(api, mcp))

        async with Client(server) as client:
            listed = await client.list_tools()
            assert listed.tools == []
            result = await client.call_tool("repo_context", {"query": "battery"})
            assert result.is_error is True
            assert "not exposed" in result.content[0].text

        assert dispatcher.calls == []

    asyncio.run(exercise())


def test_configured_mcp_server_loads_persisted_policies(tmp_path, monkeypatch) -> None:
    async def exercise() -> None:
        api_path = tmp_path / "api.toml"
        mcp_path = tmp_path / "mcp.toml"
        api, mcp = _policies()
        write_api_config(api, api_path)
        write_mcp_config(mcp, mcp_path)
        monkeypatch.setenv("GWAY_WEB_API_CONFIG", str(api_path))
        monkeypatch.setenv("GWAY_WEB_MCP_CONFIG", str(mcp_path))

        dispatcher = _Dispatcher()
        server = build_configured_mcp_server(
            dispatcher,
            authorizer=lambda context, target: True,
        )

        async with Client(server) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == ["repo_context"]
            result = await client.call_tool("repo_context", {"query": "battery"})
            assert result.is_error is False

        assert dispatcher.calls == [
            ("repo", ("context",), {"query": "battery"})
        ]

    asyncio.run(exercise())


def test_configured_mcp_server_is_empty_when_policy_files_are_absent(
    tmp_path, monkeypatch
) -> None:
    async def exercise() -> None:
        monkeypatch.setenv("GWAY_WEB_API_CONFIG", str(tmp_path / "missing-api.toml"))
        monkeypatch.setenv("GWAY_WEB_MCP_CONFIG", str(tmp_path / "missing-mcp.toml"))

        dispatcher = _Dispatcher()
        server = build_configured_mcp_server(
            dispatcher,
            authorizer=lambda context, target: True,
        )

        async with Client(server) as client:
            listed = await client.list_tools()
            assert listed.tools == []

        assert dispatcher.calls == []

    asyncio.run(exercise())


def test_streamable_http_app_uses_sdk_transport() -> None:
    dispatcher = _Dispatcher()
    api, mcp = _policies()
    server = build_mcp_server(
        dispatcher,
        api,
        mcp,
        _tools(api, mcp),
        authorizer=lambda context, target: True,
    )

    app = streamable_http_app(server)

    assert app is not None
