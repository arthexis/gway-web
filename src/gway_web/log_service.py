from __future__ import annotations

import argparse
from collections.abc import Sequence

from .logs import serve_logs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the authenticated GWAY log store")
    parser.add_argument("--source", required=True, help="resolved GWAY log-store root")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the authenticated log service using an already-resolved source."""
    arguments = _parser().parse_args(argv)
    serve_logs(source=arguments.source)


if __name__ == "__main__":
    main()
