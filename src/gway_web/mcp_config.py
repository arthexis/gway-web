"""Deny-by-default policy for agent-facing MCP exposure."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .api_config import APIConfig, _command_path, _project_key


@dataclass(frozen=True)
class MCPProjectExposure:
    """Explicit MCP exposure for one canonical GWay project."""

    name: str
    functions: frozenset[tuple[str, ...]] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _project_key(self.name))
        object.__setattr__(
            self,
            "functions",
            frozenset(_command_path(path) for path in self.functions),
        )

    def allows(self, command_path: str | Sequence[str]) -> bool:
        """Return whether one normalized command path is explicitly MCP-visible."""
        return _command_path(command_path) in self.functions


@dataclass(frozen=True)
class MCPConfig:
    """Agent exposure policy layered strictly below HTTP API exposure."""

    projects: tuple[MCPProjectExposure, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(self.projects)
        names = [project.name for project in normalized]
        if len(names) != len(set(names)):
            raise ValueError("MCP project names must be unique")
        object.__setattr__(self, "projects", normalized)

    def command_exposed(
        self,
        api_policy: APIConfig,
        canonical_project: str,
        command_path: str | Sequence[str],
    ) -> bool:
        """Return whether a command passes both HTTP and MCP allowlists."""
        project = _project_key(canonical_project)
        path = _command_path(command_path)
        if not api_policy.command_exposed(project, path):
            return False
        return any(item.name == project and item.allows(path) for item in self.projects)

    def exposed_commands(
        self,
        api_policy: APIConfig,
        canonical_project: str,
    ) -> tuple[tuple[str, ...], ...]:
        """Return deterministic commands allowed by both policy layers."""
        project = _project_key(canonical_project)
        for item in self.projects:
            if item.name == project:
                return tuple(
                    path
                    for path in sorted(item.functions)
                    if api_policy.command_exposed(project, path)
                )
        return ()


__all__ = ["MCPConfig", "MCPProjectExposure"]
