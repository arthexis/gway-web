"""GWay-facing helpers for persistent MCP exposure policy."""

from __future__ import annotations

from .mcp_config import (
    MCPConfig,
    MCPProjectExposure,
    mcp_config_path,
    read_mcp_config,
    write_mcp_config,
)


def _payload(policy: MCPConfig) -> dict[str, object]:
    return {
        "path": str(mcp_config_path()),
        "projects": [
            {
                "name": project.name,
                "functions": ["/".join(path) for path in sorted(project.functions)],
            }
            for project in policy.projects
        ],
    }


def mcp(
    *,
    project: str | None = None,
    functions: str | None = None,
) -> dict[str, object]:
    """Inspect or idempotently configure one project in the MCP exposure policy."""
    policy = read_mcp_config()
    if project is None and functions is None:
        return _payload(policy)
    if project is None:
        raise ValueError("--functions requires --project")

    key = project.strip().casefold()
    if not key:
        raise ValueError("--project must not be empty")
    projects = {item.name: item for item in policy.projects}
    existing = projects.get(key)
    if functions is None:
        selected_functions = existing.functions if existing is not None else frozenset()
    else:
        selected_functions = frozenset(
            value.strip() for value in functions.split(",") if value.strip()
        )
    projects[key] = MCPProjectExposure(name=key, functions=selected_functions)

    updated = MCPConfig(projects=tuple(sorted(projects.values(), key=lambda item: item.name)))
    write_mcp_config(updated)
    return _payload(updated)


__all__ = ["mcp"]
