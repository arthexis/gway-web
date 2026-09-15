"""Deny-by-default configuration for GWay HTTP API exposure."""

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

ENV_API_CONFIG = "GWAY_WEB_API_CONFIG"
DEFAULT_API_CONFIG = Path("~/.config/gway/api.toml").expanduser()


def api_config_path() -> Path:
    """Return the dedicated API policy path.

    API policy intentionally lives outside ``web.toml`` because the site writer
    replaces its own manifest atomically and must never erase API exposure state.
    """
    return Path(os.environ.get(ENV_API_CONFIG, DEFAULT_API_CONFIG)).expanduser()


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


def _scope(value: str | None, project: str) -> str:
    selected = value.strip() if isinstance(value, str) else f"{project}:read"
    if not selected or ":" not in selected or any(character.isspace() for character in selected):
        raise ValueError(f"invalid API token scope: {value!r}")
    return selected


@dataclass(frozen=True)
class APIProjectExposure:
    """Explicit HTTP exposure for one canonical GWay project."""

    name: str
    functions: frozenset[tuple[str, ...]] = field(default_factory=frozenset)
    scope: str | None = None

    def __post_init__(self) -> None:
        name = _project_key(self.name)
        object.__setattr__(self, "name", name)
        object.__setattr__(
            self,
            "functions",
            frozenset(_command_path(path) for path in self.functions),
        )
        object.__setattr__(self, "scope", _scope(self.scope, name))

    def allows(self, command_path: str | Sequence[str]) -> bool:
        """Return whether one normalized command path is explicitly exposed."""
        return _command_path(command_path) in self.functions


@dataclass(frozen=True)
class APIConfig:
    """Central API exposure and authentication policy."""

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
        key = _project_key(canonical_project)
        return any(project.name == key for project in self.projects)

    def project_scope(self, canonical_project: str) -> str | None:
        key = _project_key(canonical_project)
        for project in self.projects:
            if project.name == key:
                return project.scope
        return None

    def command_exposed(
        self,
        canonical_project: str,
        command_path: str | Sequence[str],
    ) -> bool:
        key = _project_key(canonical_project)
        return any(
            project.name == key and project.allows(command_path) for project in self.projects
        )

    def exposed_commands(self, canonical_project: str) -> tuple[tuple[str, ...], ...]:
        key = _project_key(canonical_project)
        for project in self.projects:
            if project.name == key:
                return tuple(sorted(project.functions))
        return ()


def read_api_config(path: str | Path | None = None) -> APIConfig:
    """Read the central API exposure policy."""
    target = Path(path).expanduser() if path is not None else api_config_path()
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
        raw_scope = values.get("scope")
        if raw_scope is not None and not isinstance(raw_scope, str):
            raise TypeError(f"api project {name!r} scope must be a string")
        projects.append(
            APIProjectExposure(
                name=name,
                functions=frozenset(_command_path(value) for value in raw_functions),
                scope=raw_scope,
            )
        )

    return APIConfig(base_domain=base_domain, projects=tuple(projects))


def write_api_config(config: APIConfig, path: str | Path | None = None) -> Path:
    """Atomically replace the dedicated API policy file."""
    target = Path(path).expanduser() if path is not None else api_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[api]"]
    if config.base_domain is not None:
        lines.append(f"base_domain = {json.dumps(config.base_domain)}")
    lines.append("")
    for project in sorted(config.projects, key=lambda item: item.name):
        lines.append(f"[api.projects.{json.dumps(project.name)}]")
        functions = ["/".join(path) for path in sorted(project.functions)]
        lines.append("functions = [" + ", ".join(json.dumps(value) for value in functions) + "]")
        lines.append(f"scope = {json.dumps(project.scope)}")
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
