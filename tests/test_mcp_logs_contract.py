from __future__ import annotations

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.mcp_config import MCPConfig, MCPProjectExposure
from gway_web.mcp_schema import tools_from_discovery


def test_explicit_log_commands_generate_narrow_mcp_surface() -> None:
    discovery = {
        "project": "web",
        "commands": [
            {
                "path": ["get-events"],
                "summary": "Read one bounded cursor page of events",
                "parameters": [
                    {"name": "run", "required": True, "positional": True, "type": "str"},
                    {
                        "name": "source",
                        "required": False,
                        "positional": False,
                        "type": "str",
                        "default": "[logs.source]",
                    },
                    {
                        "name": "after",
                        "required": False,
                        "positional": False,
                        "type": "int | None",
                        "default": None,
                    },
                    {
                        "name": "limit",
                        "required": False,
                        "positional": False,
                        "type": "int",
                        "default": 100,
                    },
                ],
            },
            {
                "path": ["get-run"],
                "summary": "Return metadata for one log run",
                "parameters": [
                    {"name": "run", "required": True, "positional": True, "type": "str"},
                    {
                        "name": "source",
                        "required": False,
                        "positional": False,
                        "type": "str",
                        "default": "[logs.source]",
                    },
                ],
            },
            {
                "path": ["list-runs"],
                "summary": "List recent log runs",
                "parameters": [
                    {
                        "name": "source",
                        "required": False,
                        "positional": False,
                        "type": "str",
                        "default": "[logs.source]",
                    },
                    {
                        "name": "limit",
                        "required": False,
                        "positional": False,
                        "type": "int",
                        "default": 100,
                    },
                ],
            },
            {
                "path": ["logs"],
                "summary": "Compatibility wrapper",
                "parameters": [],
            },
        ],
    }
    api = APIConfig(
        projects=(
            APIProjectExposure(
                "web",
                frozenset({("list-runs",), ("get-run",), ("get-events",), ("logs",)}),
            ),
        )
    )
    mcp = MCPConfig(
        projects=(
            MCPProjectExposure(
                "web",
                frozenset({("list-runs",), ("get-run",), ("get-events",)}),
            ),
        )
    )

    tools = tools_from_discovery(discovery, api_policy=api, mcp_policy=mcp)

    assert [tool["name"] for tool in tools] == [
        "web_get_events",
        "web_get_run",
        "web_list_runs",
    ]
    assert all(tool["command"] != ["logs"] for tool in tools)
