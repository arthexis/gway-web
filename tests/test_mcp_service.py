from __future__ import annotations

from types import SimpleNamespace

from gway_web.api_config import APIConfig, APIProjectExposure
from gway_web.mcp_dispatch import MCPToolTarget
from gway_web.mcp_service import _bearer_token, bearer_authorizer
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
