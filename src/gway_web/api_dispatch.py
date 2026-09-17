"""Policy-aware execution of one translated GWay API request."""

from __future__ import annotations

from typing import Protocol

from .api_config import APIConfig
from .api_routing import APIRequest

_NOT_FOUND_MESSAGE = "API route is not exposed"
_SAFE_ARGUMENT_MARKER = "transport_safe_argument_error"


class APINotFoundError(LookupError):
    """Raised when a request does not resolve to an explicitly exposed API route."""


class APIArgumentError(ValueError):
    """Transport-safe argument error whose message may be returned to API clients."""


class _ProjectLike(Protocol):
    name: str


class _RegistryLike(Protocol):
    def require(self, name_or_alias: str) -> _ProjectLike: ...


class DispatcherLike(Protocol):
    """Structural subset of GWay Dispatcher used by the API layer."""

    registry: _RegistryLike

    def invoke(
        self,
        project_name: str,
        command_path: tuple[str, ...],
        arguments: dict[str, str] | None = None,
    ) -> object: ...


def canonical_project_name(dispatcher: DispatcherLike, project_token: str) -> str:
    """Resolve one project/alias token without revealing registry lookup details."""
    try:
        project = dispatcher.registry.require(project_token)
    except ValueError:
        raise APINotFoundError(_NOT_FOUND_MESSAGE) from None

    name = getattr(project, "name", None)
    if not isinstance(name, str) or not name.strip():
        raise APINotFoundError(_NOT_FOUND_MESSAGE)
    return name


def _transport_safe_argument_error(error: BaseException) -> bool:
    """Recognize only errors explicitly classified safe by the GWay invocation boundary."""
    return getattr(type(error), _SAFE_ARGUMENT_MARKER, False) is True


def _normalized_path(path: object) -> tuple[str, ...] | None:
    if not isinstance(path, tuple) or not path or not all(isinstance(part, str) for part in path):
        return None
    return tuple(part.strip().replace("_", "-").casefold() for part in path)


def _semantic_default(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return len(text) >= 2 and text.startswith("[") and text.endswith("]")


def _server_owned_arguments(
    dispatcher: DispatcherLike,
    canonical_project: str,
    command_path: tuple[str, ...],
) -> frozenset[str]:
    """Return semantic-default parameters that remote callers may not override."""
    commands = getattr(dispatcher, "commands", None)
    if not callable(commands):
        return frozenset()
    requested = tuple(part.replace("_", "-").casefold() for part in command_path)
    for command in commands(canonical_project):
        if _normalized_path(getattr(command, "path", None)) != requested:
            continue
        return frozenset(
            parameter.name
            for parameter in getattr(command, "parameters", ())
            if _semantic_default(getattr(parameter, "default", None))
        )
    return frozenset()


def dispatch_api_request(
    dispatcher: DispatcherLike,
    policy: APIConfig,
    request: APIRequest,
) -> object:
    """Authorize and invoke exactly one translated request through GWay.

    GWay's programmatic invocation boundary marks only argument binding and
    conversion failures as transport-safe. Those are translated into the local
    ``APIArgumentError`` contract so the HTTP layer may return a bounded 400.
    All other exceptions, including ordinary ``ValueError`` from application
    callables, propagate without exposing their messages to clients.
    """
    canonical_project = canonical_project_name(dispatcher, request.project)
    if not policy.command_exposed(canonical_project, request.command_path):
        raise APINotFoundError(_NOT_FOUND_MESSAGE)

    server_owned = _server_owned_arguments(dispatcher, canonical_project, request.command_path)
    supplied_server_owned = sorted(server_owned.intersection(request.arguments))
    if supplied_server_owned:
        name = supplied_server_owned[0]
        raise APIArgumentError(f"argument {name!r} is server-managed")

    try:
        return dispatcher.invoke(
            request.project,
            request.command_path,
            dict(request.arguments),
        )
    except APIArgumentError:
        raise
    except Exception as exc:
        if _transport_safe_argument_error(exc):
            raise APIArgumentError(str(exc)) from exc
        raise
