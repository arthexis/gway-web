from __future__ import annotations

import json
from pathlib import Path

import pytest

from gway_web import commands
from gway_web.tokens import list_tokens, verify_token


def test_token_is_shown_once_and_not_stored_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = tmp_path / "tokens.json"
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(store))

    issued = commands.token(name="chatgpt-log-reader", scope="logs:read,logs:stream", ttl=3600)
    raw = str(issued["token"])

    assert raw.startswith("gweb_v1_")
    assert verify_token(raw, scope="logs:read") is True
    assert verify_token(raw, scope="logs:stream") is True
    assert verify_token(raw, scope="logs:ingest") is False
    assert raw not in store.read_text(encoding="utf-8")

    listing = list_tokens()
    assert listing[0]["name"] == "chatgpt-log-reader"
    assert "digest" not in listing[0]
    assert "token" not in listing[0]


def test_token_revoke_invalidates_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(tmp_path / "tokens.json"))
    issued = commands.token(scope="logs:read", ttl=3600)
    raw = str(issued["token"])
    token_id = str(issued["token_id"])

    commands.token(token_id, revoke=True)

    assert verify_token(raw, scope="logs:read") is False
    assert commands.token(list=True)[0]["revoked_at"] is not None


def test_token_store_contains_hash_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "tokens.json"
    monkeypatch.setenv("GWAY_WEB_TOKEN_STORE", str(store))
    issued = commands.token(name="watchtower", scope="logs:ingest", ttl=3600)

    payload = json.loads(store.read_text(encoding="utf-8"))
    record = payload["tokens"][issued["token_id"]]
    assert record["digest"]
    assert "token" not in record
    assert record["scopes"] == ["logs:ingest"]
