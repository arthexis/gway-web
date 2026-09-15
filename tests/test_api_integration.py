from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from gway_web.api_config import read_api_config
from gway_web.api_http import create_api_server
from gway_web.tokens import issue_token


@dataclass
class _Project:
    name: str


class _Registry:
    def require(self, token: str) -> _Project:
        if token.casefold() in {"repo", "gway-repo"}:
            return _Project("repo")
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


class _CoreArgumentError(ValueError):
    transport_safe_argument_error = True


class _Dispatcher:
    """Fixture matching the public signatures of gway-repo's first API commands."""

    def __init__(self) -> None:
        self.registry = _Registry()
        self.calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []

    def commands(self, project_name: str) -> tuple[_Command, ...]:
        assert project_name == "repo"
        return (
            _Command(
                ("context",),
                summary="Return one bounded context envelope for a pull request or issue.",
                parameters=(
                    _Parameter("pr", annotation=int),
                    _Parameter("issue", annotation=int),
                    _Parameter("include_impact", annotation=bool, default=True),
                ),
            ),
            _Command(
                ("impact",),
                summary="Return bounded code impact for one PR, issue, or local file.",
                parameters=(
                    _Parameter("pr", annotation=int),
                    _Parameter("issue", annotation=int),
                    _Parameter("file", annotation=str),
                    _Parameter("depth", annotation=int, default=2),
                ),
            ),
            _Command(
                ("prs",),
                summary="Return pull requests connected to an issue.",
                parameters=(
                    _Parameter("issue", required=True, positional=True, annotation=int),
                    _Parameter("limit", annotation=int, default=20),
                ),
            ),
            _Command(("reviews",), summary="Hidden repository command"),
        )

    @staticmethod
    def _integer(values: dict[str, str], name: str, *, required: bool = False) -> int | None:
        value = values.get(name)
        if value is None:
            if required:
                raise _CoreArgumentError(f"missing required arguments: {name}")
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise _CoreArgumentError(f"invalid integer argument: {name}") from exc

    def invoke(
        self,
        project_name: str,
        command_path: tuple[str, ...],
        arguments: dict[str, str] | None = None,
    ) -> object:
        values = dict(arguments or {})
        self.calls.append((project_name, command_path, values))

        if command_path == ("context",):
            return {
                "kind": "context",
                "issue": self._integer(values, "issue"),
                "requested_as": project_name,
            }
        if command_path == ("impact",):
            return {
                "kind": "impact",
                "issue": self._integer(values, "issue"),
                "depth": self._integer(values, "depth") or 2,
                "requested_as": project_name,
            }
        if command_path == ("prs",):
            return {
                "kind": "prs",
                "issue": self._integer(values, "issue", required=True),
                "requested_as": project_name,
            }
        raise ValueError("unexpected command dispatch")


@contextmanager
def _running_server(dispatcher: _Dispatcher, policy):
    previous_store = os.environ.get("GWAY_WEB_TOKEN_STORE")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["GWAY_WEB_TOKEN_STORE"] = os.path.join(directory, "tokens.json")
        token = str(issue_token(scopes="repo:read")["token"])
        server = create_api_server(dispatcher, policy, host="127.0.0.1", port=0)
        server.test_token = token
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            if previous_store is None:
                os.environ.pop("GWAY_WEB_TOKEN_STORE", None)
            else:
                os.environ["GWAY_WEB_TOKEN_STORE"] = previous_store


def _get(server, target: str, *, host: str = "repo.gway.test"):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    connection.request(
        "GET",
        target,
        headers={"Host": host, "Authorization": f"Bearer {server.test_token}"},
    )
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, body


def test_repository_api_profile_routes_only_first_three_commands(tmp_path) -> None:
    config = tmp_path / "web.toml"
    config.write_text(
        """
[api]
base_domain = "gway.test"

[api.projects.repo]
functions = ["context", "impact", "prs"]
scope = "repo:read"
""".strip(),
        encoding="utf-8",
    )
    policy = read_api_config(config)
    dispatcher = _Dispatcher()

    with _running_server(dispatcher, policy) as server:
        context_status, context = _get(server, "/context?issue=1")
        impact_status, impact = _get(server, "/impact?issue=1&depth=3")
        prs_status, prs = _get(
            server,
            "/prs?issue=1",
            host="gway-repo.gway.test",
        )
        discovery_status, discovery = _get(
            server,
            "/_gway",
            host="gway-repo.gway.test",
        )
        hidden_status, hidden = _get(server, "/reviews?number=1")
        invalid_status, invalid = _get(server, "/prs?issue=not-an-int")

    assert context_status == 200
    assert context == {
        "ok": True,
        "result": {"kind": "context", "issue": 1, "requested_as": "repo"},
    }
    assert impact_status == 200
    assert impact == {
        "ok": True,
        "result": {"kind": "impact", "issue": 1, "depth": 3, "requested_as": "repo"},
    }
    assert prs_status == 200
    assert prs == {
        "ok": True,
        "result": {"kind": "prs", "issue": 1, "requested_as": "gway-repo"},
    }

    assert discovery_status == 200
    assert discovery["ok"] is True
    assert discovery["result"]["project"] == "repo"
    assert [command["path"] for command in discovery["result"]["commands"]] == [
        ["context"],
        ["impact"],
        ["prs"],
    ]

    assert hidden_status == 404
    assert hidden == {
        "ok": False,
        "error": {"type": "not_found", "message": "API route is not exposed"},
    }

    assert invalid_status == 400
    assert invalid == {
        "ok": False,
        "error": {"type": "invalid_arguments", "message": "invalid integer argument: issue"},
    }

    assert dispatcher.calls == [
        ("repo", ("context",), {"issue": "1"}),
        ("repo", ("impact",), {"issue": "1", "depth": "3"}),
        ("gway-repo", ("prs",), {"issue": "1"}),
        ("repo", ("prs",), {"issue": "not-an-int"}),
    ]
