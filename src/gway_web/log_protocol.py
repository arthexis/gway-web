from __future__ import annotations

LOG_READ_SCOPE = "logs:read"
LOG_INGEST_SCOPE = "logs:ingest"
LOG_NDJSON_CONTENT_TYPE = "application/x-ndjson"
LOG_RUNS_PATH = "/api/logs/runs"
LOG_EVENTS_PREFIX = "/api/logs/"
LOG_EVENTS_SUFFIX = "/events"


def log_events_path(run_id: str) -> str:
    return f"{LOG_EVENTS_PREFIX}{run_id}{LOG_EVENTS_SUFFIX}"


def log_events_template(destination: str) -> str:
    return f"{destination.rstrip('/')}{LOG_EVENTS_PREFIX}{{run_id}}{LOG_EVENTS_SUFFIX}"


def publisher_configuration(destination: str) -> dict[str, object]:
    """Return the Web-owned HTTP protocol configuration for a GWAY binding."""
    return {
        "transport": "http",
        "url_template": log_events_template(destination),
        "method": "POST",
        "headers": {
            "Authorization": "Bearer {GWAY_WEB_LOG_TOKEN}",
            "Content-Type": LOG_NDJSON_CONTENT_TYPE,
        },
    }


__all__ = [
    "LOG_EVENTS_PREFIX",
    "LOG_EVENTS_SUFFIX",
    "LOG_INGEST_SCOPE",
    "LOG_NDJSON_CONTENT_TYPE",
    "LOG_READ_SCOPE",
    "LOG_RUNS_PATH",
    "log_events_path",
    "log_events_template",
    "publisher_configuration",
]
