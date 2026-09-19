from __future__ import annotations

from dataclasses import dataclass

import pytest

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.api_discovery import discover_project
from gway_web.api_dispatch import APINotFoundError


@dataclass
class _Project:
    name: str


class _Registry:
    def require(self, token: str) -> _Project:
        if token.casefold() in {"repo", "r"}:
            return _Project("repo")
        if token.casefold() == "hidden":
            return _Project("hidden")
        raise ValueError("unknown project")


@dataclass
class _Parameter:
    name: str
    required: bool = False
    positional: bool = False
    annotation: object | None = None
    default: object = None
    help: str | None = None
    negative_options: tuple[str, ...] | None = None


@dataclass
class _Command:
    path: tuple[str, ...]
    summary: str | None = None
    description: str | None = None
    parameters: tuple[_Parameter, ...] = ()


class _Dispatcher:
    def __init__(self) -> None:
        self.registry = _Registry()

    def commands(self, project_name: str) -> tuple[_Command, ...]:
        assert project_name == "repo"
        return (
            _Command(
                ("impact",),
                summary="Analyze impact",
                parameters=(
                    _Parameter("issue", required=True, positional=True, annotation=int),
                    _Parameter("depth", annotation=int, default=2),
                    _Parameter(
                        "include_tests",
                        annotation=bool,
                        default=True,
                        negative_options=("--no-include-tests",),
                    ),
                    _Parameter("source", annotation=str, default="[repo.source]"),
                ),
            ),
            _Command(("secret",), summary="Must remain hidden"),
            _Command(
                ("context",),
                parameters=(_Parameter("opaque", default=object()),),
            ),
        )

    def invoke(self, project_name, command_path, arguments=None):
        raise AssertionError("discovery must not invoke commands")


def _policy() -> APIConfig:
    return APIConfig(
        base_domain="gway.example.com",
        projects=(
            APIProjectExposure(
                "repo",
                frozenset({("impact",), ("context",)}),
            ),
        ),
    )


def test_discovery_reports_only_exposed_commands_for_canonical_project() -> None:
    result = discover_project(_Dispatcher(), _policy(), "r")

    assert result["project"] == "repo"
    commands = result["commands"]
    assert [command["path"] for command in commands] == [["context"], ["impact"]]
    assert all(command["path"] != ["secret"] for command in commands)

    impact = commands[1]
    assert impact["summary"] == "Analyze impact"
    assert impact["parameters"] == [
        {
            "name": "issue",
            "required": True,
            "positional": True,
            "type": "int",
        },
        {
            "name": "depth",
            "required": False,
            "positional": False,
            "type": "int",
            "default": 2,
        },
        {
            "name": "include_tests",
            "required": False,
            "positional": False,
            "type": "bool",
            "default": True,
            "negative_options": ["--no-include-tests"],
        },
    ]
    assert all(parameter["name"] != "source" for parameter in impact["parameters"])


def test_discovery_omits_non_json_defaults() -> None:
    result = discover_project(_Dispatcher(), _policy(), "repo")

    context = result["commands"][0]
    assert context["path"] == ["context"]
    assert "default" not in context["parameters"][0]


def test_discovery_hides_known_but_unexposed_projects() -> None:
    with pytest.raises(APINotFoundError, match="not exposed"):
        discover_project(_Dispatcher(), _policy(), "hidden")
