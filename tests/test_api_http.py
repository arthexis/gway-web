from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.api_http import create_api_server


@dataclass
class _Project:
    name: str


class _Registry:
    def require(self, token: str) -> _Project:
        if token.casefold() in {"repo", "r"}:
            return _Project("repo")
        raise ValueError("project is not registered")


class _Dispatcher:
    def __init__(self) -> None:
        self.registry = _Registry()
        self.calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
        self.result: object = {"status": "ok"}
        self.error: Exception | None = None

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


@contextmanager
def _running_server(
    dispatcher: _Dispatcher,
    *,
    max_response_bytes: int = 1024 * 1024,
):
    server = create_api_server(
        dispatcher,
        _policy(),
        host="127.0.0.1",
        port=0,
        max_response_bytes=max_response_bytes,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    server,
    method: str,
    target: str,
    *,
    host: str = "repo.gway.example.com",
):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    connection.request(method, target, headers={"Host": host})
    response = connection.getresponse()
    body = response.read()
    headers = dict(response.getheaders())
    connection.close()
    return response.status, headers, json.loads(body.decode("utf-8"))


def test_get_executes_one_exposed_call_and_returns_json_envelope() -> None:
    dispatcher = _Dispatcher()
    dispatcher.result = {"issue": 917, "depth": 2}

    with _running_server(dispatcher) as server:
        status, headers, body = _request(server, "GET", "/impact?issue=917&depth=2")

    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Cache-Control"] == "no-store"
    assert body == {"ok": True, "result": {"issue": 917, "depth": 2}}
    assert dispatcher.calls == [("repo", ("impact",), {"issue": "917", "depth": "2"})]


def test_alias_host_routes_through_original_alias_token() -> None:
    dispatcher = _Dispatcher()

    with _running_server(dispatcher) as server:
        status, _, body = _request(
            server,
            "GET",
            "/context?issue=1",
            host="r.gway.example.com",
        )

    assert status == 200
    assert body["ok"] is True
    assert dispatcher.calls == [("r", ("context",), {"issue": "1"})]


def test_unknown_and_unexposed_routes_share_generic_404() -> None:
    dispatcher = _Dispatcher()

    with _running_server(dispatcher) as server:
        unknown = _request(
            server,
            "GET",
            "/impact",
            host="missing.gway.example.com",
        )
        unexposed = _request(server, "GET", "/secret")

    for status, _, body in (unknown, unexposed):
        assert status == 404
        assert body == {
            "ok": False,
            "error": {"type": "not_found", "message": "API route is not exposed"},
        }
    assert dispatcher.calls == []


def test_invalid_request_syntax_maps_to_400_without_dispatch() -> None:
    dispatcher = _Dispatcher()

    with _running_server(dispatcher) as server:
        status, _, body = _request(server, "GET", "/impact+-+context")

    assert status == 400
    assert body["ok"] is False
    assert body["error"]["type"] == "invalid_request"
    assert dispatcher.calls == []


def test_invocation_value_errors_map_to_invalid_arguments() -> None:
    dispatcher = _Dispatcher()
    dispatcher.error = ValueError("missing required arguments: issue")

    with _running_server(dispatcher) as server:
        status, _, body = _request(server, "GET", "/impact")

    assert status == 400
    assert body == {
        "ok": False,
        "error": {
            "type": "invalid_arguments",
            "message": "missing required arguments: issue",
        },
    }


def test_unexpected_errors_do_not_leak_internal_details() -> None:
    dispatcher = _Dispatcher()
    dispatcher.error = RuntimeError("secret stack detail")

    with _running_server(dispatcher) as server:
        status, _, body = _request(server, "GET", "/impact")

    assert status == 500
    assert body == {
        "ok": False,
        "error": {"type": "internal_error", "message": "request execution failed"},
    }
    assert "secret stack detail" not in json.dumps(body)


def test_unsupported_methods_return_json_405_and_allow_get() -> None:
    dispatcher = _Dispatcher()

    with _running_server(dispatcher) as server:
        status, headers, body = _request(server, "POST", "/impact")

    assert status == 405
    assert headers["Allow"] == "GET"
    assert body == {
        "ok": False,
        "error": {"type": "method_not_allowed", "message": "only GET is supported"},
    }
    assert dispatcher.calls == []


def test_non_json_results_return_bounded_structured_error() -> None:
    dispatcher = _Dispatcher()
    dispatcher.result = object()

    with _running_server(dispatcher) as server:
        status, _, body = _request(server, "GET", "/impact")

    assert status == 500
    assert body == {
        "ok": False,
        "error": {
            "type": "invalid_result",
            "message": "callable result is not JSON serializable",
        },
    }


def test_oversized_results_return_error_instead_of_large_body() -> None:
    dispatcher = _Dispatcher()
    dispatcher.result = {"payload": "x" * 4096}

    with _running_server(dispatcher, max_response_bytes=256) as server:
        status, headers, body = _request(server, "GET", "/impact")

    assert status == 500
    assert int(headers["Content-Length"]) <= 256
    assert body == {
        "ok": False,
        "error": {
            "type": "response_too_large",
            "message": "callable result exceeds response limit",
        },
    }


def test_server_requires_base_domain_and_sensible_response_limit() -> None:
    dispatcher = _Dispatcher()

    with pytest.raises(ValueError, match="base_domain"):
        create_api_server(dispatcher, APIConfig(), port=0)

    with pytest.raises(ValueError, match="max_response_bytes"):
        create_api_server(dispatcher, _policy(), port=0, max_response_bytes=128)
