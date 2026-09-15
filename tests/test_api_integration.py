from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from gway_web.api_config import read_api_config
from gway_web.api_http import create_api_server


@dataclass
class _Project:
    name: str


class _Registry:
    def require(self, token: str) -> _Project:
        if token.casefold() in {"repo", "r"}:
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


class _Dispatcher:
    def __init__(self) -> None:
        self.registry = _Registry()
        self.calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []

    def commands(self, project_name: str) -> tuple[_Command, ...]:
        assert project_name == "repo"
        return (
            _Command(
                ("impact",),
                summary="Analyze issue impact",
                parameters=(
                    _Parameter("issue", required=True, positional=True, annotation=int),
                    _Parameter("depth", annotation=int, default=2),
                ),
            ),
            _Command(("secret",), summary="Hidden command"),
        )

    def invoke(
        self,
        project_name: str,
        command_path: tuple[str, ...],
        arguments: dict[str, str] | None = None,
    ) -> object:
        values = dict(arguments or {})
        self.calls.append((project_name, command_path, values))
        if command_path != ("impact",):
            raise ValueError("unknown command")
        return {
            "issue": int(values["issue"]),
            "depth": int(values.get("depth", "2")),
            "requested_as": project_name,
        }


@contextmanager
def _running_server(dispatcher: _Dispatcher, policy):
    server = create_api_server(dispatcher, policy, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(server, target: str, *, host: str = "repo.gway.test"):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    connection.request("GET", target, headers={"Host": host})
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, body


def test_config_to_http_to_dispatch_and_discovery_end_to_end(tmp_path) -> None:
    config = tmp_path / "web.toml"
    config.write_text(
        """
[api]
base_domain = "gway.test"

[api.projects.repo]
functions = ["impact"]
""".strip(),
        encoding="utf-8",
    )
    policy = read_api_config(config)
    dispatcher = _Dispatcher()

    with _running_server(dispatcher, policy) as server:
        status, body = _get(
            server,
            "/impact?issue=917&depth=3",
            host="r.gway.test",
        )
        discovery_status, discovery = _get(server, "/_gway", host="r.gway.test")
        hidden_status, hidden = _get(server, "/secret", host="repo.gway.test")

    assert status == 200
    assert body == {
        "ok": True,
        "result": {"issue": 917, "depth": 3, "requested_as": "r"},
    }
    assert dispatcher.calls == [("r", ("impact",), {"issue": "917", "depth": "3"})]

    assert discovery_status == 200
    assert discovery["ok"] is True
    assert discovery["result"]["project"] == "repo"
    assert [command["path"] for command in discovery["result"]["commands"]] == [["impact"]]

    assert hidden_status == 404
    assert hidden == {
        "ok": False,
        "error": {"type": "not_found", "message": "API route is not exposed"},
    }
