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
        "public_hosts": list(policy.public_hosts),
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
    host: str | None = None,
) -> dict[str, object]:
    """Inspect or idempotently configure MCP project exposure and public hosts."""
    policy = read_mcp_config()
    if project is None and functions is None and host is None:
        return _payload(policy)
    if project is None and functions is not None:
        raise ValueError("--functions requires --project")

    projects = {item.name: item for item in policy.projects}
    if project is not None:
        key = project.strip().casefold()
        if not key:
            raise ValueError("--project must not be empty")
        existing = projects.get(key)
        if functions is None:
            selected_functions = existing.functions if existing is not None else frozenset()
        else:
            selected_functions = frozenset(
                value.strip() for value in functions.split(",") if value.strip()
            )
        projects[key] = MCPProjectExposure(name=key, functions=selected_functions)

    public_hosts = policy.public_hosts
    if host is not None:
        values = tuple(value.strip() for value in host.split(",") if value.strip())
        if not values:
            raise ValueError("--host must contain at least one hostname")
        public_hosts = values

    updated = MCPConfig(
        projects=tuple(sorted(projects.values(), key=lambda item: item.name)),
        public_hosts=public_hosts,
    )
    write_mcp_config(updated)
    return _payload(updated)


__all__ = ["mcp"]
