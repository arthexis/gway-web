"""HTTP transport for the authenticated single-call GWay API."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .api_config import APIConfig
from .api_discovery import discover_project
from .api_dispatch import (
    APIArgumentError,
    APINotFoundError,
    DispatcherLike,
    canonical_project_name,
    dispatch_api_request,
)
from .api_routing import APITranslationError, project_from_host, translate_request
from .tokens import verify_token

LOGGER = logging.getLogger(__name__)
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
_MIN_MAX_RESPONSE_BYTES = 256
_MAX_ERROR_MESSAGE_BYTES = 128


class _ResponseTooLargeError(ValueError):
    pass


def _encode_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _encode_json_bounded(payload: object, max_bytes: int) -> bytes:
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    body = bytearray()
    for chunk in encoder.iterencode(payload):
        encoded = chunk.encode("utf-8")
        if len(body) + len(encoded) > max_bytes:
            raise _ResponseTooLargeError
        body.extend(encoded)
    return bytes(body)


def _bounded_message(value: object) -> str:
    raw = str(value).encode("utf-8", errors="replace")
    if len(raw) <= _MAX_ERROR_MESSAGE_BYTES:
        return raw.decode("utf-8")
    prefix = raw[: _MAX_ERROR_MESSAGE_BYTES - 3].decode("utf-8", errors="ignore")
    return f"{prefix}..."


def _error_payload(error_type: str, message: str) -> dict[str, object]:
    return {
        "ok": False,
        "error": {"type": error_type, "message": message},
    }


class GWayAPIRequestHandler(BaseHTTPRequestHandler):
    """Serve one bearer-authenticated GWay callable per HTTP request."""

    dispatcher: DispatcherLike
    policy: APIConfig
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _write_bytes(
        self,
        status: int,
        body: bytes,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _write_error(
        self,
        status: int,
        error_type: str,
        message: str,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = _encode_json(_error_payload(error_type, _bounded_message(message)))
        if len(body) > self.max_response_bytes:
            body = _encode_json(_error_payload("internal_error", "response could not be encoded"))
            status = 500
            extra_headers = None
        self._write_bytes(status, body, extra_headers=extra_headers)

    def _write_result(self, result: object) -> None:
        try:
            body = _encode_json_bounded(
                {"ok": True, "result": result},
                self.max_response_bytes,
            )
        except _ResponseTooLargeError:
            self._write_error(500, "response_too_large", "callable result exceeds response limit")
            return
        except (TypeError, ValueError, OverflowError):
            self._write_error(500, "invalid_result", "callable result is not JSON serializable")
            return
        self._write_bytes(200, body)

    def _method_not_allowed(self) -> None:
        self.close_connection = True
        self._write_error(
            405,
            "method_not_allowed",
            "only GET is supported",
            extra_headers={"Allow": "GET"},
        )

    def _project_token(self) -> str:
        return project_from_host(
            self.headers.get("Host", ""),
            self.policy.base_domain or "",
        )

    def _authorize(self, project_token: str) -> bool:
        canonical = canonical_project_name(self.dispatcher, project_token)
        if not self.policy.project_exposed(canonical):
            raise APINotFoundError("API route is not exposed")
        scope = self.policy.project_scope(canonical)
        if scope is None:
            raise APINotFoundError("API route is not exposed")

        authorization = self.headers.get("Authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        valid_shape = (
            bool(separator)
            and scheme.casefold() == "bearer"
            and bool(credential)
            and credential.strip() == credential
            and not any(character.isspace() for character in credential)
        )
        if not valid_shape or not verify_token(credential, scope=scope):
            self._write_error(
                401,
                "unauthorized",
                "valid bearer token required",
                extra_headers={"WWW-Authenticate": "Bearer"},
            )
            return False
        return True

    def _discovery(self, target, project_token: str) -> object:
        if target.query:
            raise APITranslationError("/_gway does not accept query parameters")
        return discover_project(
            self.dispatcher,  # type: ignore[arg-type]
            self.policy,
            project_token,
        )

    def do_GET(self) -> None:  # noqa: N802
        try:
            target = urlsplit(self.path)
        except ValueError:
            self._write_error(400, "invalid_request", "invalid request target")
            return

        if target.path == "/health":
            self._write_result({"service": "gway-web-api", "status": "ok"})
            return

        try:
            project_token = self._project_token()
            if not self._authorize(project_token):
                return
            if target.path == "/_gway":
                result = self._discovery(target, project_token)
            else:
                request = translate_request(
                    host=self.headers.get("Host", ""),
                    path=target.path,
                    query=target.query,
                    base_domain=self.policy.base_domain or "",
                )
                result = dispatch_api_request(self.dispatcher, self.policy, request)
        except APINotFoundError:
            self._write_error(404, "not_found", "API route is not exposed")
            return
        except APITranslationError as exc:
            self._write_error(400, "invalid_request", str(exc))
            return
        except APIArgumentError as exc:
            self._write_error(400, "invalid_arguments", str(exc))
            return
        except Exception:
            LOGGER.exception("unexpected error while executing GWay API request")
            self._write_error(500, "internal_error", "request execution failed")
            return

        self._write_result(result)

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_POST(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_TRACE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_CONNECT(self) -> None:  # noqa: N802
        self._method_not_allowed()


def create_api_server(
    dispatcher: DispatcherLike,
    policy: APIConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8050,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> ThreadingHTTPServer:
    if policy.base_domain is None:
        raise ValueError("API base_domain must be configured before starting the server")
    if not isinstance(max_response_bytes, int) or max_response_bytes < _MIN_MAX_RESPONSE_BYTES:
        raise ValueError(
            f"max_response_bytes must be an integer >= {_MIN_MAX_RESPONSE_BYTES}"
        )

    class Handler(GWayAPIRequestHandler):
        pass

    Handler.dispatcher = dispatcher
    Handler.policy = policy
    Handler.max_response_bytes = max_response_bytes
    return ThreadingHTTPServer((host, port), Handler)


def serve_api(
    dispatcher: DispatcherLike,
    policy: APIConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8050,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> None:
    server = create_api_server(
        dispatcher,
        policy,
        host=host,
        port=port,
        max_response_bytes=max_response_bytes,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
