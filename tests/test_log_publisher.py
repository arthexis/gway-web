from __future__ import annotations

import pytest

from gway_web.log_publisher import WebLogPublisherProvider


def test_web_log_publisher_owns_route_headers_and_ingest_credential() -> None:
    calls: list[dict[str, object]] = []

    def issue(**kwargs):
        calls.append(kwargs)
        return {
            "token": "gweb_v1_fixture_secret",
            "token_id": "fixture-token",
        }

    provider = WebLogPublisherProvider(credential_issuer=issue)
    binding = provider.provision(
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
    provider = WebLogPublisherProvider(
        credential_issuer=lambda **_kwargs: {
            "token": "secret",
            "token_id": "token-1",
        }
    )

    record = provider.provision(
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
    provider = WebLogPublisherProvider(
        credential_issuer=lambda **_kwargs: {
            "token": "secret",
            "token_id": "token-1",
        }
    )

    with pytest.raises(ValueError, match=r"HTTP\(S\) URL|loopback"):
        provider.provision(destination=destination, consumer="wire")


def test_web_log_publisher_rejects_incomplete_credential() -> None:
    provider = WebLogPublisherProvider(
        credential_issuer=lambda **_kwargs: {"token_id": "token-1"}
    )

    with pytest.raises(ValueError, match="no token"):
        provider.provision(
            destination="https://logs.example.test",
            consumer="wire",
        )
