from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from gway_web import Site, health, status


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        code = 200 if self.path == "/health" else 404
        self.send_response(code)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def test_status_and_health_against_local_server() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        site = Site(name="local", host="127.0.0.1", port=server.server_port, health_path="/health")
        assert status(site, timeout=1)
        result = health(site, timeout=1)
        assert result.ok
        assert result.status_code == 200
        assert result.error is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_unreachable_site_is_reported_without_raising() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_port
    server.server_close()
    site = Site(name="missing", host="127.0.0.1", port=port)
    assert not status(site, timeout=0.1)
    result = health(site, timeout=0.1)
    assert not result.ok
    assert result.status_code is None
    assert result.error
