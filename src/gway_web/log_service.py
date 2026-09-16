from __future__ import annotations

from .log_query import log_source
from .logs import serve_logs


def main() -> None:
    """Run the authenticated log service on its loopback default."""
    serve_logs(source=log_source())


if __name__ == "__main__":
    main()
