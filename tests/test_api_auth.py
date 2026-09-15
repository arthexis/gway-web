from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from gway_web.api_config import (
    APIConfig,
    APIProjectExposure,
    read_api_config,
    write_api_config,
)
from gway_web.api_http import create_api_server
from gway_web.tokens import issue_token, provision_token, verify_token


@dataclass
class _Project:
    name: str


class _Registry:
    def require(self, token: str) -> _Project:
        if token.casefold() in {"repo", "gway-repo"}:
            return _Project("repo")
        raise ValueError("unknown project")


class _Dispatcher:
    def __init__(self) -> None:
        self.registry = _Registry()

    def invoke(self, project_name, command_path, arguments=None):
        return {
            "project": project_name,
            "command": list(command_path),
            **dict(arguments or {}),
        }


@contextmanager
def _running_server(policy):
    server = create_api_server(_Dispatcher(), policy, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get(server, target: str, *, token: str | None = None):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=2
    )
    headers = {"Host": "repo.gway.test"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    connection.request("GET", target, headers=headers)
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    headers = dict(response.getheaders())
    connection.close()
    return response.status, body, headers


def test_repo_routes_require_project_scoped_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(tmp_path / "tokens.json"))
    policy = APIConfig(
        base_domain="gway.test",
        projects=(
            APIProjectExposure("repo", frozenset({("context",)}), "repo:read"),
        ),
    )
    repo_token = issue_token(scopes="repo:read")["token"]
    wrong_token = issue_token(scopes="logs:read")["token"]

    with _running_server(policy) as server:
        health_status, health, _ = _get(server, "/health")
        missing_status, missing, missing_headers = _get(server, "/context?issue=1")
        wrong_status, _, _ = _get(
            server, "/context?issue=1", token=str(wrong_token)
        )
        ok_status, ok, _ = _get(server, "/context?issue=1", token=str(repo_token))

    assert health_status == 200
    assert health["result"]["service"] == "gway-web-api"
    assert missing_status == 401
    assert missing["error"]["type"] == "unauthorized"
    assert missing_headers["WWW-Authenticate"] == "Bearer"
    assert wrong_status == 401
    assert ok_status == 200
    assert ok["result"]["issue"] == "1"


def test_provision_token_is_idempotent_and_never_returns_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(tmp_path / "tokens.json"))
    issued = issue_token(scopes="repo:read")
    token = str(issued["token"])
    first = provision_token(token, name="repo-api", scopes="repo:read")
    second = provision_token(token, name="repo-api", scopes="repo:read")

    assert first["token_id"] == second["token_id"] == issued["token_id"]
    assert "token" not in first
    assert verify_token(token, scope="repo:read")


def test_provision_token_rejects_low_entropy_external_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(tmp_path / "tokens.json"))

    with pytest.raises(ValueError, match="high-entropy"):
        provision_token("gweb_v1_abcdef123456_guessme", scopes="repo:read")


def test_api_policy_uses_dedicated_config_path(tmp_path, monkeypatch):
    site_config = tmp_path / "web.toml"
    api_config = tmp_path / "api.toml"
    site_config.write_text(
        "[sites.demo]\ndomain = \"example.test\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GWAY_WEB_API_CONFIG", str(api_config))

    policy = APIConfig(
        base_domain="example.test",
        projects=(
            APIProjectExposure("repo", frozenset({("context",)}), "repo:read"),
        ),
    )
    write_api_config(policy)

    assert read_api_config() == policy
    assert "[api]" not in site_config.read_text(encoding="utf-8")
    assert api_config.stat().st_mode & 0o077 == 0
