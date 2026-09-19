from __future__ import annotations

import pytest

from gway_web.api_config import APIConfig, APIProjectExposure, read_api_config


def test_api_policy_is_deny_by_default() -> None:
    policy = APIConfig()

    assert policy.base_domain is None
    assert not policy.project_exposed("repo")
    assert not policy.command_exposed("repo", ("context",))
    assert policy.exposed_commands("repo") == ()


def test_read_api_policy_allowlists_canonical_project_commands(tmp_path) -> None:
    config = tmp_path / "web.toml"
    config.write_text(
        """
[api]
base_domain = "GWAY.EXAMPLE.COM."

[api.projects.repo]
functions = ["context", "impact", "prs", "admin/status"]
""".strip(),
        encoding="utf-8",
    )

    policy = read_api_config(config)

    assert policy.base_domain == "gway.example.com"
    assert policy.project_exposed("repo")
    assert policy.command_exposed("repo", "context")
    assert policy.command_exposed("REPO", ("impact",))
    assert policy.command_exposed("repo", ("admin", "status"))
    assert policy.exposed_commands("repo") == (
        ("admin", "status"),
        ("context",),
        ("impact",),
        ("prs",),
    )


def test_policy_normalizes_command_spelling_without_widening_project_access() -> None:
    policy = APIConfig(
        projects=(
            APIProjectExposure(
                name="repo",
                functions=frozenset({("include_impact",), ("admin", "status")}),
            ),
        )
    )

    assert policy.command_exposed("repo", "include-impact")
    assert policy.command_exposed("repo", "include_impact")
    assert policy.command_exposed("repo", "admin/status")

    # Alias resolution belongs to GWay. The policy only accepts the canonical
    # project name so an alias cannot create an independent exposure surface.
    assert not policy.project_exposed("r")
    assert not policy.command_exposed("r", "include-impact")


def test_explicit_project_with_no_functions_exposes_no_commands(tmp_path) -> None:
    config = tmp_path / "web.toml"
    config.write_text("[api.projects.repo]\n", encoding="utf-8")

    policy = read_api_config(config)

    assert policy.project_exposed("repo")
    assert not policy.command_exposed("repo", "context")
    assert policy.exposed_commands("repo") == ()


def test_missing_api_section_remains_deny_by_default(tmp_path) -> None:
    config = tmp_path / "web.toml"
    config.write_text(
        """
[sites.demo]
domain = "example.com"
host = "127.0.0.1"
port = 8000
""".strip(),
        encoding="utf-8",
    )

    assert read_api_config(config) == APIConfig()


def test_invalid_api_project_functions_are_rejected(tmp_path) -> None:
    config = tmp_path / "web.toml"
    config.write_text(
        """
[api.projects.repo]
functions = "context"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(TypeError, match="functions must be an array of strings"):
        read_api_config(config)


def test_duplicate_canonical_project_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="project names must be unique"):
        APIConfig(
            projects=(
                APIProjectExposure("Repo"),
                APIProjectExposure("repo"),
            )
        )


def test_invalid_command_paths_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        APIProjectExposure("repo", frozenset({""}))

    with pytest.raises(ValueError, match="non-empty string components"):
        APIProjectExposure("repo", frozenset({("admin", "")}))
