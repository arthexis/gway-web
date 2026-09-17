"""Discovery for explicitly exposed GWay API callables."""

from __future__ import annotations

import json
from typing import Protocol

from .api_config import APIConfig
from .api_dispatch import APINotFoundError, DispatcherLike, canonical_project_name


class _ParameterLike(Protocol):
    name: str
    required: bool
    positional: bool
    annotation: object | None
    default: object
    help: str | None
    negative_options: tuple[str, ...] | None


class _CommandLike(Protocol):
    path: tuple[str, ...]
    summary: str | None
    description: str | None
    parameters: tuple[_ParameterLike, ...]


class DiscoveryDispatcherLike(DispatcherLike, Protocol):
    def commands(self, project_name: str) -> tuple[_CommandLike, ...]: ...


def _annotation_name(annotation: object | None) -> str | None:
    if annotation is None:
        return None
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str) and name:
        return name
    text = str(annotation).replace("typing.", "")
    return text if len(text) <= 128 else f"{text[:125]}..."


def _safe_default(parameter: _ParameterLike) -> tuple[bool, object | None]:
    if parameter.required:
        return False, None
    value = parameter.default
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return False, None
    return True, value


def _semantic_default(parameter: _ParameterLike) -> bool:
    """Return whether a parameter default is a server-resolved GWay Sigil."""
    if parameter.required or not isinstance(parameter.default, str):
        return False
    value = parameter.default.strip()
    return len(value) >= 2 and value.startswith("[") and value.endswith("]")


def _parameter_payload(parameter: _ParameterLike) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": parameter.name,
        "required": bool(parameter.required),
        "positional": bool(parameter.positional),
    }
    annotation = _annotation_name(parameter.annotation)
    if annotation is not None:
        payload["type"] = annotation
    if parameter.help:
        payload["description"] = parameter.help
    has_default, default = _safe_default(parameter)
    if has_default:
        payload["default"] = default
    if parameter.negative_options:
        payload["negative_options"] = list(parameter.negative_options)
    return payload


def _command_payload(command: _CommandLike) -> dict[str, object]:
    payload: dict[str, object] = {
        "path": list(command.path),
        "parameters": [
            _parameter_payload(parameter)
            for parameter in command.parameters
            if not _semantic_default(parameter)
        ],
    }
    if command.summary:
        payload["summary"] = command.summary
    if command.description:
        payload["description"] = command.description
    return payload


def discover_project(
    dispatcher: DiscoveryDispatcherLike,
    policy: APIConfig,
    project_token: str,
) -> dict[str, object]:
    """Describe only explicitly exposed commands for one resolved project/alias."""
    canonical_project = canonical_project_name(dispatcher, project_token)
    if not policy.project_exposed(canonical_project):
        raise APINotFoundError("API route is not exposed")

    commands = [
        command
        for command in dispatcher.commands(canonical_project)
        if policy.command_exposed(canonical_project, command.path)
    ]
    commands.sort(key=lambda command: tuple(part.casefold() for part in command.path))
    return {
        "project": canonical_project,
        "commands": [_command_payload(command) for command in commands],
    }
