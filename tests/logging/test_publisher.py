from __future__ import annotations

from pathlib import Path

import pytest

from gway_web import commands
from gway_web.log_protocol import LOG_INGEST_SCOPE, publisher_configuration
from gway_web.log_publisher import WebLogPublisherProvider
from gway_web.log_publisher_state import publisher_store_path
from gway_web.tokens import revoke_token


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GWAY_WEB_LOG_PUBLISHER_STORE",
        str(tmp_path / "log-publishers.json"),
    )
    monkeypatch.setenv(
        "GWAY_WEB_TOKEN_STORE",
        str(tmp_path / "tokens.json"),
    )


def _credential(token: str = "secret", token_id: str = "token-1") -> dict[str, str]:
    return {"token": token, "token_id": token_id}


def _provider(**kwargs) -> WebLogPublisherProvider:
    kwargs.setdefault("credential_issuer", lambda **_kwargs: _credential())
    return WebLogPublisherProvider(**kwargs)


def test_web_log_publisher_owns_route_headers_and_ingest_credential() -> None:
    calls: list[dict[str, object]] = []

    def issue(**kwargs):
        calls.append(kwargs)
        return _credential("gweb_v1_fixture_secret", "fixture-token")

    binding = WebLogPublisherProvider(credential_issuer=issue).provision(
        destination="https://logs.example.test/",
        consumer="wire",
    )

    assert calls == [{"name": "gway-consumer:wire", "scopes": "logs:ingest"}]
    assert binding.provider == "web"
    assert binding.destination == "https://logs.example.test"
    assert binding.configuration == {
        "transport": "http",
        "url_template": "https://logs.example.test/api/logs/{run_id}/events",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer {GWAY_WEB_LOG_TOKEN}",
            "Content-Type": "application/x-ndjson",
        },
    }
    assert binding.environment == {"GWAY_WEB_LOG_TOKEN": "gweb_v1_fixture_secret"}
    assert binding.metadata == {"token_id": "fixture-token"}


def test_web_log_publisher_record_matches_gway_binding_wire_shape() -> None:
    record = _provider().provision(
        destination="http://127.0.0.1:8040",
        consumer="wire",
    ).to_record()

    assert set(record) == {
        "provider",
        "destination",
        "configuration",
        "environment",
        "metadata",
    }
    assert record["provider"] == "web"
    assert record["destination"] == "http://127.0.0.1:8040"


@pytest.mark.parametrize(
    "destination",
    [
        "logs.example.test",
        "ftp://logs.example.test",
        "https:///missing-host",
        "http://logs.example.test",
    ],
)
def test_web_log_publisher_rejects_invalid_destination(destination: str) -> None:
    with pytest.raises(ValueError, match=r"HTTP\(S\) URL|loopback"):
        _provider().provision(destination=destination, consumer="wire")


def test_web_log_publisher_rejects_incomplete_credential() -> None:
    provider = WebLogPublisherProvider(
        credential_issuer=lambda **_kwargs: {"token_id": "token-1"}
    )

    with pytest.raises(ValueError, match="no token"):
        provider.provision(
            destination="https://logs.example.test",
            consumer="wire",
        )


def test_web_log_publisher_reuses_valid_provider_binding() -> None:
    issued: list[dict[str, object]] = []

    def issue(**kwargs):
        issued.append(kwargs)
        return _credential("valid-secret")

    provider = _provider(
        credential_issuer=issue,
        credential_verifier=lambda token, *, scope=None: (
            token == "valid-secret" and scope == "logs:ingest"
        ),
    )

    first = provider.provision(
        destination="https://logs.example.test",
        consumer="wire",
    )
    second = provider.provision(
        destination="https://logs.example.test",
        consumer="wire",
    )

    assert second == first
    assert issued == [{"name": "gway-consumer:wire", "scopes": "logs:ingest"}]


def test_web_log_publisher_rotates_invalid_provider_binding() -> None:
    counter = 0

    def issue(**_kwargs):
        nonlocal counter
        counter += 1
        return _credential(f"secret-{counter}", f"token-{counter}")

    valid_tokens = {"secret-1"}
    provider = _provider(
        credential_issuer=issue,
        credential_verifier=lambda token, *, scope=None: (
            token in valid_tokens and scope == "logs:ingest"
        ),
    )

    first = provider.provision(
        destination="https://logs.example.test",
        consumer="wire",
    )
    valid_tokens.clear()
    second = provider.provision(
        destination="https://logs.example.test",
        consumer="wire",
    )

    assert first.metadata["token_id"] == "token-1"
    assert second.metadata["token_id"] == "token-2"
    assert second.environment["GWAY_WEB_LOG_TOKEN"] == "secret-2"


def test_web_log_publisher_rotates_revoked_real_token() -> None:
    provider = WebLogPublisherProvider()

    first = provider.provision(
        destination="https://logs.example.test",
        consumer="wire",
    )
    first_token_id = str(first.metadata["token_id"])
    revoke_token(first_token_id)

    second = provider.provision(
        destination="https://logs.example.test",
        consumer="wire",
    )

    assert second.metadata["token_id"] != first_token_id
    assert second.environment["GWAY_WEB_LOG_TOKEN"] != first.environment["GWAY_WEB_LOG_TOKEN"]


def test_web_log_publisher_private_store_permissions(tmp_path: Path) -> None:
    _provider(
        credential_verifier=lambda _token, *, scope=None: scope == "logs:ingest",
    ).provision(
        destination="https://logs.example.test",
        consumer="wire",
    )

    path = publisher_store_path()
    assert path == tmp_path / "log-publishers.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"


def test_web_log_publisher_state_is_scoped_by_consumer_and_destination() -> None:
    counter = 0

    def issue(**_kwargs):
        nonlocal counter
        counter += 1
        return _credential(f"secret-{counter}", f"token-{counter}")

    provider = _provider(
        credential_issuer=issue,
        credential_verifier=lambda _token, *, scope=None: scope == "logs:ingest",
    )

    bindings = [
        provider.provision(
            destination="https://logs.example.test",
            consumer="wire",
        ),
        provider.provision(
            destination="https://logs.example.test",
            consumer="arthexis",
        ),
        provider.provision(
            destination="http://127.0.0.1:8040",
            consumer="wire",
        ),
    ]

    assert {binding.metadata["token_id"] for binding in bindings} == {
        "token-1",
        "token-2",
        "token-3",
    }


def test_log_publisher_command_reuses_provider_owned_binding() -> None:
    first = commands.log_publisher(
        destination="https://logs.example.test",
        consumer="wire",
    )
    second = commands.log_publisher(
        destination="https://logs.example.test",
        consumer="wire",
    )

    assert second == first
    assert first["provider"] == "web"
    assert first["configuration"] == {
        "transport": "http",
        "url_template": "https://logs.example.test/api/logs/{run_id}/events",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer {GWAY_WEB_LOG_TOKEN}",
            "Content-Type": "application/x-ndjson",
        },
    }
    environment = first["environment"]
    assert isinstance(environment, dict)
    token = environment["GWAY_WEB_LOG_TOKEN"]
    assert isinstance(token, str)
    assert token.startswith("gweb_v1_")


def test_web_publisher_uses_web_owned_protocol_configuration() -> None:
    binding = _provider(
        credential_issuer=lambda **_kwargs: _credential("fixture-value", "fixture-id"),
        credential_verifier=lambda _token, *, scope=None: scope == LOG_INGEST_SCOPE,
    ).provision(
        destination="https://logs.example.test",
        consumer="wire",
    )

    assert binding.configuration == publisher_configuration(
        "https://logs.example.test"
    )
