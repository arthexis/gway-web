"""Pure translation from HTTP request components to one GWay invocation target."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote

_COMMAND_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_ARGUMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_MAX_QUERY_FIELDS = 64


class APITranslationError(ValueError):
    """Raised when HTTP request components cannot name one safe GWay call."""


@dataclass(frozen=True)
class APIRequest:
    """One transport-neutral single-call request produced from HTTP components."""

    project: str
    command_path: tuple[str, ...]
    arguments: dict[str, str]


def _validate_percent_encoding(value: str, field: str) -> None:
    index = 0
    while True:
        index = value.find("%", index)
        if index < 0:
            return
        if _PERCENT_ESCAPE.match(value, index) is None:
            raise APITranslationError(f"invalid percent escape in {field}")
        index += 3


def project_from_host(host: str, base_domain: str) -> str:
    """Extract exactly one project/alias DNS label from an HTTP Host value."""
    if not isinstance(host, str) or not host.strip():
        raise APITranslationError("Host must be a non-empty string")
    if not isinstance(base_domain, str) or not base_domain.strip():
        raise APITranslationError("API base domain must be configured")

    value = host.strip()
    if any(character in value for character in "/@[]"):
        raise APITranslationError("Host must contain only a hostname and optional port")

    if value.count(":") > 1:
        raise APITranslationError("IPv6 hosts cannot identify a project subdomain")
    hostname, separator, port = value.partition(":")
    if separator and (not port.isdigit() or not 1 <= int(port) <= 65535):
        raise APITranslationError("Host contains an invalid port")

    hostname = hostname.rstrip(".").casefold()
    domain = base_domain.strip().rstrip(".").casefold()
    if not hostname or not domain:
        raise APITranslationError("Host and API base domain must not be empty")
    if hostname == domain:
        raise APITranslationError("Host must contain exactly one valid project subdomain")

    suffix = f".{domain}"
    if not hostname.endswith(suffix):
        raise APITranslationError("Host is outside the configured API domain")

    project = hostname[: -len(suffix)]
    if not project or "." in project or _HOST_LABEL.fullmatch(project) is None:
        raise APITranslationError("Host must contain exactly one valid project subdomain")
    return project


def command_from_path(path: str) -> tuple[str, ...]:
    """Translate one URL path into exactly one normalized GWay command path."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise APITranslationError("API path must start with '/'")
    if "?" in path or "#" in path:
        raise APITranslationError("API path must not include query or fragment data")
    if path == "/" or path.endswith("/") or "//" in path:
        raise APITranslationError("API path must identify exactly one command")

    raw_parts = path[1:].split("/")
    parts: list[str] = []
    for index, raw_part in enumerate(raw_parts):
        _validate_percent_encoding(raw_part, "path")
        part = unquote(raw_part)
        if len(raw_parts) == 1 and index == 0 and part.casefold() == "_gway":
            raise APITranslationError("/_gway is reserved for API discovery")
        if _COMMAND_COMPONENT.fullmatch(part) is None:
            raise APITranslationError(f"invalid command path component: {part!r}")
        parts.append(part.replace("_", "-").casefold())

    return tuple(parts)


def query_arguments(query: str) -> dict[str, str]:
    """Decode a URL query into unique named string arguments for GWay."""
    if not isinstance(query, str):
        raise APITranslationError("query must be a string")
    if query.startswith("?"):
        query = query[1:]
    if not query:
        return {}

    _validate_percent_encoding(query, "query")
    try:
        pairs = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_MAX_QUERY_FIELDS,
        )
    except ValueError as exc:
        raise APITranslationError(f"invalid query string: {exc}") from exc

    arguments: dict[str, str] = {}
    for raw_name, value in pairs:
        if _ARGUMENT_NAME.fullmatch(raw_name) is None:
            raise APITranslationError(f"invalid query parameter name: {raw_name!r}")
        name = raw_name.replace("_", "-").casefold()
        if name in arguments:
            raise APITranslationError(f"duplicate query parameter: {raw_name}")
        arguments[name] = value
    return arguments


def translate_request(
    *,
    host: str,
    path: str,
    query: str = "",
    base_domain: str,
) -> APIRequest:
    """Translate HTTP request components without performing policy or dispatch."""
    return APIRequest(
        project=project_from_host(host, base_domain),
        command_path=command_from_path(path),
        arguments=query_arguments(query),
    )
