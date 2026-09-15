"""Deny-by-default configuration for GWay HTTP API exposure."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from .config import config_path


def _project_key(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("API project name must be a non-empty string")
    return name.strip().casefold()


def _command_path(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("API command path must not be empty")
        if "/" in text:
            parts = tuple(part.strip() for part in text.split("/"))
        else:
            parts = tuple(text.split())
    else:
        parts = tuple(value)

    if not parts or any(not isinstance(part, str) or not part.strip() for part in parts):
        raise ValueError("API command path must contain non-empty string components")
    return tuple(part.strip().replace("_", "-").casefold() for part in parts)


@dataclass(frozen=True)
class APIProjectExposure:
    """Explicit HTTP exposure for one canonical GWay project."""

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
        """Return whether one normalized command path is explicitly exposed."""
        return _command_path(command_path) in self.functions


@dataclass(frozen=True)
class APIConfig:
    """Central API exposure policy.

    Projects and commands are absent unless explicitly configured. Callers must
    resolve project aliases through GWay first and query this policy with the
    resulting canonical project name.
    """

    base_domain: str | None = None
    projects: tuple[APIProjectExposure, ...] = ()

    def __post_init__(self) -> None:
        if self.base_domain is not None:
            if not isinstance(self.base_domain, str) or not self.base_domain.strip():
                raise ValueError("API base_domain must be a non-empty string")
            object.__setattr__(self, "base_domain", self.base_domain.strip().rstrip(".").casefold())

        normalized = tuple(self.projects)
        names = [project.name for project in normalized]
        if len(names) != len(set(names)):
            raise ValueError("API project names must be unique")
        object.__setattr__(self, "projects", normalized)

    def project_exposed(self, canonical_project: str) -> bool:
        """Return whether a canonical project has an explicit API entry."""
        key = _project_key(canonical_project)
        return any(project.name == key for project in self.projects)

    def command_exposed(
        self,
        canonical_project: str,
        command_path: str | Sequence[str],
    ) -> bool:
        """Return whether a canonical project command is explicitly allowlisted."""
        key = _project_key(canonical_project)
        return any(
            project.name == key and project.allows(command_path) for project in self.projects
        )

    def exposed_commands(self, canonical_project: str) -> tuple[tuple[str, ...], ...]:
        """Return sorted exposed command paths for one canonical project."""
        key = _project_key(canonical_project)
        for project in self.projects:
            if project.name == key:
                return tuple(sorted(project.functions))
        return ()


def read_api_config(path: str | Path | None = None) -> APIConfig:
    """Read the central API exposure policy from the gway-web TOML config."""
    target = Path(path).expanduser() if path is not None else config_path()
    if not target.exists():
        if path is None:
            return APIConfig()
        raise FileNotFoundError(target)

    with target.open("rb") as stream:
        data = tomllib.load(stream)

    raw_api = data.get("api")
    if raw_api is None:
        return APIConfig()
    if not isinstance(raw_api, dict):
        raise TypeError("api must be a TOML table")

    base_domain = raw_api.get("base_domain")
    if base_domain is not None and (not isinstance(base_domain, str) or not base_domain.strip()):
        raise TypeError("api.base_domain must be a non-empty string")

    raw_projects = raw_api.get("projects", {})
    if not isinstance(raw_projects, dict):
        raise TypeError("api.projects must be a TOML table")

    projects: list[APIProjectExposure] = []
    for name, values in raw_projects.items():
        if not isinstance(values, dict):
            raise TypeError(f"api project {name!r} must be a TOML table")
        raw_functions = values.get("functions", [])
        if not isinstance(raw_functions, list) or not all(
            isinstance(value, str) and value.strip() for value in raw_functions
        ):
            raise TypeError(f"api project {name!r} functions must be an array of strings")
        projects.append(
            APIProjectExposure(
                name=name,
                functions=frozenset(_command_path(value) for value in raw_functions),
            )
        )

    return APIConfig(base_domain=base_domain, projects=tuple(projects))
