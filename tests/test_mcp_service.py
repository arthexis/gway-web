from __future__ import annotations

from types import SimpleNamespace

from starlette.testclient import TestClient

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.mcp_config import MCPConfig
from gway_web.mcp_dispatch import MCPToolTarget
from gway_web.mcp_service import _bearer_token, bearer_authorizer, build_service_app
from gway_web.tokens import issue_token


def _context(authorization: str | None):
    headers = {} if authorization is None else {"Authorization": authorization}
    return SimpleNamespace(request=SimpleNamespace(headers=headers))


def test_bearer_token_parser_rejects_malformed_credentials() -> None:
    assert _bearer_token(None) is None
    assert _bearer_token({}) is None
    assert _bearer_token({"Authorization": "Basic abc"}) is None
    assert _bearer_token({"Authorization": "Bearer"}) is None
    assert _bearer_token({"Authorization": "Bearer a b"}) is None
    assert _bearer_token({"Authorization": "Bearer abc"}) == "abc"


def test_mcp_bearer_authorizer_uses_target_project_scope(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(tmp_path / "tokens.json"))
    issued = issue_token(name="logs", scopes="logs:read")
    token = str(issued["token"])
    policy = APIConfig(
        projects=(
            APIProjectExposure("web", frozenset({("list-runs",)}), "logs:read"),
            APIProjectExposure("repo", frozenset({("context",)}), "repo:read"),
        )
    )
    authorize = bearer_authorizer(policy)
    context = _context(f"Bearer {token}")

    assert authorize(context, MCPToolTarget("web_list_runs", "web", ("list-runs",))) is True
    assert authorize(context, MCPToolTarget("repo_context", "repo", ("context",))) is False
    assert authorize(context, None) is False
    assert authorize(_context(None), MCPToolTarget("web_list_runs", "web", ("list-runs",))) is False


def test_service_app_exposes_health_for_existing_web_exposure() -> None:
    app = build_service_app(
        SimpleNamespace(),
        api_policy=APIConfig(),
        mcp_policy=MCPConfig(public_hosts=("mcp.example.com",)),
    )

    with TestClient(app, base_url="http://mcp.example.com") as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"service": "gway-web-mcp", "status": "ok"}


def test_service_app_rejects_unconfigured_public_host_before_mcp_dispatch() -> None:
    app = build_service_app(
        SimpleNamespace(),
        api_policy=APIConfig(),
        mcp_policy=MCPConfig(public_hosts=("mcp.example.com",)),
    )

    with TestClient(app, base_url="http://wrong.example.com") as client:
        response = client.post("/mcp", json={})

    assert response.status_code == 421
