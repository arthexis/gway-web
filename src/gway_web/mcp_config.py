"""Deny-by-default policy for agent-facing MCP exposure."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from .api_config import APIConfig, _command_path, _project_key

ENV_MCP_CONFIG = "GWAY_WEB_MCP_CONFIG"
DEFAULT_MCP_CONFIG = Path("~/.config/gway/mcp.toml").expanduser()


def mcp_config_path() -> Path:
    """Return the dedicated MCP exposure-policy path."""
    return Path(os.environ.get(ENV_MCP_CONFIG, DEFAULT_MCP_CONFIG)).expanduser()


def _public_host(value: str) -> str:
    selected = value.strip().lower().rstrip(".")
    if not selected or any(character.isspace() for character in selected):
        raise ValueError("MCP public host must be a non-empty hostname")
    if "/" in selected or "://" in selected:
        raise ValueError("MCP public host must be a hostname, not a URL")
    return selected


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
    public_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(self.projects)
        names = [project.name for project in normalized]
        if len(names) != len(set(names)):
            raise ValueError("MCP project names must be unique")
        object.__setattr__(self, "projects", normalized)
        hosts = tuple(dict.fromkeys(_public_host(value) for value in self.public_hosts))
        object.__setattr__(self, "public_hosts", hosts)

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


def read_mcp_config(path: str | Path | None = None) -> MCPConfig:
    """Read the dedicated MCP exposure policy, denying everything when absent."""
    target = Path(path).expanduser() if path is not None else mcp_config_path()
    if not target.exists():
        if path is None:
            return MCPConfig()
        raise FileNotFoundError(target)

    with target.open("rb") as stream:
        data = tomllib.load(stream)

    raw_mcp = data.get("mcp")
    if raw_mcp is None:
        return MCPConfig()
    if not isinstance(raw_mcp, dict):
        raise TypeError("mcp must be a TOML table")

    raw_hosts = raw_mcp.get("public_hosts", [])
    if not isinstance(raw_hosts, list) or not all(
        isinstance(value, str) and value.strip() for value in raw_hosts
    ):
        raise TypeError("mcp.public_hosts must be an array of hostnames")

    raw_projects = raw_mcp.get("projects", {})
    if not isinstance(raw_projects, dict):
        raise TypeError("mcp.projects must be a TOML table")

    projects: list[MCPProjectExposure] = []
    for name, values in raw_projects.items():
        if not isinstance(values, dict):
            raise TypeError(f"mcp project {name!r} must be a TOML table")
        raw_functions = values.get("functions", [])
        if not isinstance(raw_functions, list) or not all(
            isinstance(value, str) and value.strip() for value in raw_functions
        ):
            raise TypeError(f"mcp project {name!r} functions must be an array of strings")
        projects.append(
            MCPProjectExposure(
                name=name,
                functions=frozenset(_command_path(value) for value in raw_functions),
            )
        )

    return MCPConfig(
        projects=tuple(projects),
        public_hosts=tuple(raw_hosts),
    )


def write_mcp_config(config: MCPConfig, path: str | Path | None = None) -> Path:
    """Atomically replace the dedicated MCP exposure policy file."""
    target = Path(path).expanduser() if path is not None else mcp_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[mcp]"]
    if config.public_hosts:
        hosts = ", ".join(json.dumps(value) for value in config.public_hosts)
        lines.append(f"public_hosts = [{hosts}]")
    lines.append("")
    for project in sorted(config.projects, key=lambda item: item.name):
        lines.append(f"[mcp.projects.{json.dumps(project.name)}]")
        functions = ["/".join(path) for path in sorted(project.functions)]
        lines.append("functions = [" + ", ".join(json.dumps(value) for value in functions) + "]")
        lines.append("")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise
    return target


__all__ = [
    "DEFAULT_MCP_CONFIG",
    "ENV_MCP_CONFIG",
    "MCPConfig",
    "MCPProjectExposure",
    "mcp_config_path",
    "read_mcp_config",
    "write_mcp_config",
]
