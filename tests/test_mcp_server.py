from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mcp import Client

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.mcp_config import MCPConfig, MCPProjectExposure
from gway_web.mcp_schema import tools_from_discovery
from gway_web.mcp_server import build_mcp_server, streamable_http_app


@dataclass
class _Project:
    name: str


class _Registry:
    def require(self, token: str) -> _Project:
        if token == "repo":
            return _Project("repo")
        raise ValueError("unknown project")


class _Dispatcher:
    def __init__(self) -> None:
        self.registry = _Registry()
        self.calls = []

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
