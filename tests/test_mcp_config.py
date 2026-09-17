from __future__ import annotations

import pytest

from gway_web import commands
from gway_web.mcp_config import (
    MCPConfig,
    MCPProjectExposure,
    read_mcp_config,
    write_mcp_config,
)
from gway_web.mcp_commands import mcp


def test_mcp_policy_is_deny_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GWAY_WEB_MCP_CONFIG", str(tmp_path / "missing.toml"))

    assert read_mcp_config() == MCPConfig()


def test_mcp_policy_round_trips_canonical_project_commands(tmp_path) -> None:
    path = tmp_path / "mcp.toml"
    policy = MCPConfig(
        projects=(
            MCPProjectExposure(
                "Web",
                frozenset({("list_runs",), ("get-run",), ("get_events",)}),
            ),
        )
    )

    write_mcp_config(policy, path)
    loaded = read_mcp_config(path)

    assert loaded.projects[0].name == "web"
    assert loaded.projects[0].functions == frozenset(
        {("list-runs",), ("get-run",), ("get-events",)}
    )
    assert path.stat().st_mode & 0o777 == 0o600


def test_invalid_mcp_functions_are_rejected(tmp_path) -> None:
    path = tmp_path / "mcp.toml"
    path.write_text('[mcp.projects.web]\nfunctions = "list-runs"\n', encoding="utf-8")

    with pytest.raises(TypeError, match="functions must be an array of strings"):
        read_mcp_config(path)


def test_mcp_command_is_exposed_through_gway_command_module() -> None:
    assert commands.mcp is mcp


def test_mcp_command_configures_read_only_log_tools(tmp_path, monkeypatch) -> None:
    path = tmp_path / "mcp.toml"
    monkeypatch.setenv("GWAY_WEB_MCP_CONFIG", str(path))

    result = commands.mcp(project="web", functions="list-runs,get-run,get-events")

    assert result["projects"] == [
        {
            "name": "web",
            "functions": ["get-events", "get-run", "list-runs"],
        }
    ]
    assert read_mcp_config(path).projects[0].functions == frozenset(
        {("list-runs",), ("get-run",), ("get-events",)}
    )


def test_mcp_command_requires_project_for_functions(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GWAY_WEB_MCP_CONFIG", str(tmp_path / "mcp.toml"))

    with pytest.raises(ValueError, match="requires --project"):
        mcp(functions="list-runs")
