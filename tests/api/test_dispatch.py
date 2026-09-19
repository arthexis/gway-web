from __future__ import annotations

from dataclasses import dataclass

import pytest

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.api_dispatch import (
    APIArgumentError,
    APINotFoundError,
    canonical_project_name,
    dispatch_api_request,
)
from gway_web.api_routing import APIRequest


@dataclass(frozen=True)
class _Project:
    name: str


@dataclass(frozen=True)
class _Parameter:
    name: str
    default: object = None


@dataclass(frozen=True)
class _Command:
    path: tuple[str, ...]
    parameters: tuple[_Parameter, ...] = ()


class _Registry:
    def __init__(self, projects: dict[str, _Project]) -> None:
        self.projects = projects

    def require(self, name_or_alias: str) -> _Project:
        try:
            return self.projects[name_or_alias.casefold()]
        except KeyError as exc:
            raise ValueError(f"project is not registered: {name_or_alias}") from exc


class _Dispatcher:
    def __init__(self, projects: dict[str, _Project], result: object = None) -> None:
        self.registry = _Registry(projects)
        self.result = result
        self.calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
        self.error: Exception | None = None
        self.command_metadata: tuple[_Command, ...] = ()

    def commands(self, project_name: str) -> tuple[_Command, ...]:
        return self.command_metadata

    def invoke(
        self,
        project_name: str,
        command_path: tuple[str, ...],
        arguments: dict[str, str] | None = None,
    ) -> object:
        self.calls.append((project_name, command_path, dict(arguments or {})))
        if self.error is not None:
            raise self.error
        return self.result


class _CoreArgumentError(ValueError):
    transport_safe_argument_error = True


def _policy(*functions: tuple[str, ...], project: str = "repo") -> APIConfig:
    return APIConfig(
        projects=(
            APIProjectExposure(
                project,
                frozenset(functions),
            ),
        )
    )


def test_dispatch_invokes_one_exposed_canonical_project_command() -> None:
    dispatcher = _Dispatcher({"repo": _Project("repo")}, result={"ok": "result"})
    request = APIRequest(
        project="repo",
        command_path=("impact",),
        arguments={"issue": "917", "depth": "2"},
    )

    result = dispatch_api_request(dispatcher, _policy(("impact",)), request)

    assert result == {"ok": "result"}
    assert dispatcher.calls == [
        ("repo", ("impact",), {"issue": "917", "depth": "2"})
    ]


def test_alias_resolves_to_canonical_policy_but_invokes_with_original_alias() -> None:
    project = _Project("repo")
    dispatcher = _Dispatcher({"repo": project, "r": project}, result="done")
    request = APIRequest("r", ("context",), {"issue": "31"})

    assert dispatch_api_request(dispatcher, _policy(("context",)), request) == "done"
    assert dispatcher.calls == [("r", ("context",), {"issue": "31"})]


def test_alias_cannot_widen_exposure_with_its_own_policy_entry() -> None:
    project = _Project("repo")
    dispatcher = _Dispatcher({"repo": project, "r": project})
    request = APIRequest("r", ("impact",), {})

    with pytest.raises(APINotFoundError, match="API route is not exposed"):
        dispatch_api_request(dispatcher, _policy(("impact",), project="r"), request)

    assert dispatcher.calls == []


def test_unexposed_command_is_rejected_before_dispatch() -> None:
    dispatcher = _Dispatcher({"repo": _Project("repo")})
    request = APIRequest("repo", ("admin", "status"), {})

    with pytest.raises(APINotFoundError, match="API route is not exposed"):
        dispatch_api_request(dispatcher, _policy(("impact",)), request)

    assert dispatcher.calls == []


def test_unknown_project_is_hidden_as_generic_not_found() -> None:
    dispatcher = _Dispatcher({})

    with pytest.raises(APINotFoundError, match="API route is not exposed"):
        canonical_project_name(dispatcher, "missing")


def test_dispatch_preserves_literal_argument_values() -> None:
    dispatcher = _Dispatcher({"repo": _Project("repo")}, result=True)
    request = APIRequest(
        "repo",
        ("context",),
        {"literal": "[project.name]", "include-impact": "false"},
    )

    assert dispatch_api_request(dispatcher, _policy(("context",)), request) is True
    assert dispatcher.calls == [
        (
            "repo",
            ("context",),
            {"literal": "[project.name]", "include-impact": "false"},
        )
    ]


def test_dispatch_rejects_server_owned_semantic_default_override() -> None:
    dispatcher = _Dispatcher({"web": _Project("web")}, result=True)
    dispatcher.command_metadata = (
        _Command(
            ("get-events",),
            parameters=(
                _Parameter("run"),
                _Parameter("source", "[logs.source]"),
            ),
        ),
    )
    request = APIRequest(
        "web",
        ("get-events",),
        {"run": "run-1", "source": "/etc"},
    )

    with pytest.raises(APIArgumentError, match="server-managed"):
        dispatch_api_request(dispatcher, _policy(("get-events",), project="web"), request)

    assert dispatcher.calls == []


def test_transport_safe_core_argument_error_maps_to_api_argument_error() -> None:
    dispatcher = _Dispatcher({"repo": _Project("repo")})
    dispatcher.error = _CoreArgumentError("invalid int value for issue")
    request = APIRequest("repo", ("impact",), {"issue": "not-an-int"})

    with pytest.raises(APIArgumentError, match="invalid int value for issue"):
        dispatch_api_request(dispatcher, _policy(("impact",)), request)

    assert dispatcher.calls == [("repo", ("impact",), {"issue": "not-an-int"})]


def test_unclassified_value_error_propagates_without_transport_mapping() -> None:
    dispatcher = _Dispatcher({"repo": _Project("repo")})
    dispatcher.error = ValueError("private application detail")
    request = APIRequest("repo", ("impact",), {})

    with pytest.raises(ValueError, match="private application detail") as exc_info:
        dispatch_api_request(dispatcher, _policy(("impact",)), request)

    assert type(exc_info.value) is ValueError
    assert dispatcher.calls == [("repo", ("impact",), {})]
