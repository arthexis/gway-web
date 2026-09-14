from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TOKEN_STORE_ENV = "GWAY_WEB_TOKEN_STORE"
_TOKEN_PREFIX = "gweb_v1"
_DEFAULT_TTL = 90 * 24 * 60 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def token_store_path() -> Path:
    configured = os.environ.get(_TOKEN_STORE_ENV)
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home).expanduser() / "gway-web" / "tokens.json"
    return Path.home() / ".local" / "state" / "gway-web" / "tokens.json"


def _read_store(path: Path | None = None) -> dict[str, dict[str, object]]:
    target = path or token_store_path()
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    records = payload.get("tokens", {})
    return records if isinstance(records, dict) else {}


def _write_store(records: dict[str, dict[str, object]], path: Path | None = None) -> None:
    target = path or token_store_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.parent.chmod(0o700)
    data = json.dumps({"tokens": records}, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(target, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, data.encode("utf-8"))
    finally:
        os.close(descriptor)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_scopes(scopes: str | tuple[str, ...]) -> tuple[str, ...]:
    values = scopes.split(",") if isinstance(scopes, str) else scopes
    cleaned = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    if not cleaned:
        raise ValueError("at least one token scope is required")
    for value in cleaned:
        if ":" not in value or any(character.isspace() for character in value):
            raise ValueError(f"invalid token scope: {value}")
    return cleaned


def issue_token(
    *,
    name: str | None = None,
    scopes: str | tuple[str, ...] = "logs:read",
    ttl: int = _DEFAULT_TTL,
) -> dict[str, object]:
    if ttl <= 0:
        raise ValueError("token ttl must be greater than zero")
    selected_scopes = _parse_scopes(scopes)
    token_id = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    token = f"{_TOKEN_PREFIX}_{token_id}_{secret}"
    created = _now()
    expires = created + timedelta(seconds=ttl)
    records = _read_store()
    records[token_id] = {
        "name": name or token_id,
        "digest": _digest(token),
        "scopes": list(selected_scopes),
        "created_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "last_used_at": None,
        "revoked_at": None,
    }
    _write_store(records)
    return {
        "token_id": token_id,
        "name": name or token_id,
        "token": token,
        "scopes": list(selected_scopes),
        "expires_at": expires.isoformat(),
    }


def list_tokens() -> list[dict[str, object]]:
    records = _read_store()
    return [
        {"token_id": token_id, **{key: value for key, value in record.items() if key != "digest"}}
        for token_id, record in sorted(records.items())
    ]


def revoke_token(token_id: str) -> dict[str, object]:
    records = _read_store()
    try:
        record = records[token_id]
    except KeyError as exc:
        raise KeyError(f"unknown token: {token_id}") from exc
    if record.get("revoked_at") is None:
        record["revoked_at"] = _now().isoformat()
        _write_store(records)
    return {"token_id": token_id, "revoked_at": record.get("revoked_at")}


def verify_token(token: str, *, scope: str | None = None) -> bool:
    parts = token.split("_", 3)
    if len(parts) != 4 or f"{parts[0]}_{parts[1]}" != _TOKEN_PREFIX:
        return False
    token_id = parts[2]
    records = _read_store()
    record = records.get(token_id)
    if record is None or record.get("revoked_at") is not None:
        return False
    digest = record.get("digest")
    if not isinstance(digest, str) or not secrets.compare_digest(digest, _digest(token)):
        return False
    expires_at = record.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    try:
        if datetime.fromisoformat(expires_at) <= _now():
            return False
    except ValueError:
        return False
    scopes = record.get("scopes", [])
    if scope is not None and (not isinstance(scopes, list) or scope not in scopes):
        return False
    record["last_used_at"] = _now().isoformat()
    _write_store(records)
    return True
