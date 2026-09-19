from __future__ import annotations

import pytest

from gway_web.api_routing import (
    APIRequest,
    APITranslationError,
    command_from_path,
    project_from_host,
    query_arguments,
    translate_request,
)


def test_project_from_host_extracts_one_project_label() -> None:
    assert project_from_host("repo.gway.example.com", "gway.example.com") == "repo"
    assert project_from_host("OCPP.GWAY.EXAMPLE.COM.:8443", "GWAY.EXAMPLE.COM.") == "ocpp"


def test_project_from_host_rejects_wrong_bare_or_nested_domains() -> None:
    with pytest.raises(APITranslationError, match="outside the configured API domain"):
        project_from_host("repo.example.com", "gway.example.com")

    with pytest.raises(APITranslationError, match="exactly one valid project subdomain"):
        project_from_host("gway.example.com", "gway.example.com")

    with pytest.raises(APITranslationError, match="exactly one valid project subdomain"):
        project_from_host("admin.repo.gway.example.com", "gway.example.com")


def test_project_from_host_validates_optional_port_and_host_shape() -> None:
    with pytest.raises(APITranslationError, match="invalid port"):
        project_from_host("repo.gway.example.com:abc", "gway.example.com")

    with pytest.raises(APITranslationError, match="invalid port"):
        project_from_host("repo.gway.example.com:70000", "gway.example.com")

    with pytest.raises(APITranslationError, match="hostname and optional port"):
        project_from_host("repo@gway.example.com", "gway.example.com")


def test_command_from_path_supports_single_and_nested_commands() -> None:
    assert command_from_path("/context") == ("context",)
    assert command_from_path("/Admin_Status/Current") == ("admin-status", "current")


def test_command_from_path_rejects_ambiguous_or_composed_paths() -> None:
    for path in (
        "/",
        "/impact/",
        "/admin//status",
        "/impact+-+context",
        "/impact%20-%20context",
        "/impact;context",
        "/%5Bproject.name%5D",
        "/admin%2Fstatus",
    ):
        with pytest.raises(APITranslationError):
            command_from_path(path)


def test_command_from_path_reserves_discovery_endpoint() -> None:
    with pytest.raises(APITranslationError, match="reserved for API discovery"):
        command_from_path("/_gway")


def test_command_from_path_rejects_invalid_percent_escapes() -> None:
    with pytest.raises(APITranslationError, match="invalid percent escape"):
        command_from_path("/bad%2")


def test_query_arguments_decodes_named_string_values_only() -> None:
    arguments = query_arguments(
        "issue=917&depth=2&include_impact=false&name=hello+world&"
        "literal=%5Bproject.name%5D"
    )

    assert arguments == {
        "issue": "917",
        "depth": "2",
        "include-impact": "false",
        "name": "hello world",
        "literal": "[project.name]",
    }


def test_query_arguments_accepts_blank_values_and_optional_question_mark() -> None:
    assert query_arguments("?name=") == {"name": ""}
    assert query_arguments("") == {}


def test_query_arguments_rejects_duplicate_normalized_names() -> None:
    with pytest.raises(APITranslationError, match="duplicate query parameter"):
        query_arguments("include-impact=true&include_impact=false")


def test_query_arguments_rejects_missing_values_invalid_names_and_percent_escapes() -> None:
    with pytest.raises(APITranslationError, match="invalid query string"):
        query_arguments("issue")

    with pytest.raises(APITranslationError, match="invalid query parameter name"):
        query_arguments("bad.name=value")

    with pytest.raises(APITranslationError, match="invalid percent escape"):
        query_arguments("name=%ZZ")


def test_translate_request_combines_pure_request_components() -> None:
    request = translate_request(
        host="repo.gway.example.com:443",
        path="/impact",
        query="issue=917&depth=2",
        base_domain="gway.example.com",
    )

    assert request == APIRequest(
        project="repo",
        command_path=("impact",),
        arguments={"issue": "917", "depth": "2"},
    )
