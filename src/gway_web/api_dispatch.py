"""Policy-aware execution of one translated GWay API request."""

from __future__ import annotations

from typing import Protocol

from .api_config import APIConfig
from .api_routing import APIRequest

_NOT_FOUND_MESSAGE = "API route is not exposed"


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


def dispatch_api_request(
    dispatcher: DispatcherLike,
    policy: APIConfig,
    request: APIRequest,
) -> object:
    """Authorize and invoke exactly one translated request through GWay.

    Dispatcher implementations may raise ``APIArgumentError`` only for
    validation failures whose messages are explicitly safe to return to an
    untrusted transport client. Other callable exceptions must propagate.
    """
    canonical_project = canonical_project_name(dispatcher, request.project)
    if not policy.command_exposed(canonical_project, request.command_path):
        raise APINotFoundError(_NOT_FOUND_MESSAGE)

    return dispatcher.invoke(
        request.project,
        request.command_path,
        dict(request.arguments),
    )
