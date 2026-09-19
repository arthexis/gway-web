from __future__ import annotations

import importlib.util
from pathlib import Path

from gway.project import Project
from gway.service import ServiceManager

from gway_web import commands


def _service_keys(tmp_path: Path) -> set[str]:
    root = Path(__file__).resolve().parents[1]
    project = Project.from_path(root)
    manager = ServiceManager(
        project,
        all_services=True,
        unit_directory=tmp_path / "systemd",
    )
    return {unit.key for unit in manager.units}


def test_web_services_exclude_removed_log_service(tmp_path: Path) -> None:
    assert _service_keys(tmp_path) == {"api", "mcp"}
    assert callable(commands.log_publisher)


def test_removed_log_service_entrypoint_stays_absent() -> None:
    assert importlib.util.find_spec("gway_web.log_service") is None
