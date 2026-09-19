from __future__ import annotations

from dataclasses import dataclass

import pytest

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.mcp_config import MCPConfig, MCPProjectExposure
from gway_web.mcp_dispatch import (
    MCPToolArgumentError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
    dispatch_mcp_tool,
    targets_from_tools,
)


@dataclass
class _Project:
    name: str


class _Registry:
    def require(self, token: str) -> _Project:
        if token.casefold() in {"repo", "r"}:
            return _Project("repo")
        raise ValueError("unknown project")


class _SafeBindingError(ValueError):
    transport_safe_argument_error = True


class _Dispatcher:
    def __init__(self) -> None:
        self.registry = _Registry()
        self.calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
        self.failure: BaseException | None = None
        self.result: object = {"ok": True}

    def invoke(self, project_name, command_path, arguments=None):
        self.calls.append((project_name, command_path, dict(arguments or {})))
        if self.failure is not None:
            raise self.failure
        return self.result


def _api(*functions: tuple[str, ...]) -> APIConfig:
    return APIConfig(projects=(APIProjectExposure("repo", frozenset(functions)),))


def _mcp(*functions: tuple[str, ...]) -> MCPConfig:
    return MCPConfig(projects=(MCPProjectExposure("repo", frozenset(functions)),))


def _targets():
    return targets_from_tools(
        [
            {
                "name": "repo_context",
                "project": "repo",
                "command": ["context"],
            }
        ]
    )


def test_mcp_dispatch_reuses_api_dispatch_path_and_stringifies_scalars() -> None:
    dispatcher = _Dispatcher()

    result = dispatch_mcp_tool(
        dispatcher,
        _api(("context",)),
        _mcp(("context",)),
        _targets(),
        "repo_context",
        {"depth": 2, "include_tests": False, "query": "battery"},
    )

    assert result == {"ok": True}
    assert dispatcher.calls == [
        (
            "repo",
            ("context",),
            {"depth": "2", "include_tests": "false", "query": "battery"},
        )
    ]


def test_mcp_dispatch_denies_unknown_or_mcp_hidden_tool_before_invocation() -> None:
    dispatcher = _Dispatcher()

    with pytest.raises(MCPToolNotFoundError, match="not exposed"):
        dispatch_mcp_tool(
            dispatcher,
            _api(("context",)),
            _mcp(),
            _targets(),
            "repo_context",
        )
    with pytest.raises(MCPToolNotFoundError, match="not exposed"):
        dispatch_mcp_tool(
            dispatcher,
            _api(("context",)),
            _mcp(("context",)),
            _targets(),
            "missing",
        )

    assert dispatcher.calls == []


def test_mcp_dispatch_translates_only_transport_safe_argument_errors() -> None:
    dispatcher = _Dispatcher()
    dispatcher.failure = _SafeBindingError("depth must be an integer")

    with pytest.raises(MCPToolArgumentError, match="depth must be an integer"):
        dispatch_mcp_tool(
            dispatcher,
            _api(("context",)),
            _mcp(("context",)),
            _targets(),
            "repo_context",
            {"depth": "bad"},
        )


def test_mcp_dispatch_suppresses_internal_exception_details() -> None:
    dispatcher = _Dispatcher()
    dispatcher.failure = RuntimeError("database password is secret")

    with pytest.raises(MCPToolExecutionError) as caught:
        dispatch_mcp_tool(
            dispatcher,
            _api(("context",)),
            _mcp(("context",)),
            _targets(),
            "repo_context",
        )

    assert str(caught.value) == "MCP tool execution failed"
    assert "password" not in str(caught.value)


def test_mcp_dispatch_rejects_structured_argument_values() -> None:
    dispatcher = _Dispatcher()

    with pytest.raises(MCPToolArgumentError, match="unsupported argument"):
        dispatch_mcp_tool(
            dispatcher,
            _api(("context",)),
            _mcp(("context",)),
            _targets(),
            "repo_context",
            {"payload": {"unsafe": True}},
        )

    assert dispatcher.calls == []


def test_mcp_dispatch_bounds_structured_results() -> None:
    dispatcher = _Dispatcher()
    dispatcher.result = {"data": "x" * (256 * 1024)}

    with pytest.raises(MCPToolExecutionError, match="response limit"):
        dispatch_mcp_tool(
            dispatcher,
            _api(("context",)),
            _mcp(("context",)),
            _targets(),
            "repo_context",
        )
