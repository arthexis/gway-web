from __future__ import annotations

from .logs import serve_logs


def main() -> None:
    """Run the authenticated log service on its loopback default."""
    serve_logs()


if __name__ == "__main__":
    main()
