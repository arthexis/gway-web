from __future__ import annotations

from pathlib import Path

from gway.project import Project
from gway.service import ServiceManager

from gway_web import commands


def test_web_services_are_ordinary_and_provider_is_adapter_capability(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    project = Project.from_path(root)
    manager = ServiceManager(
        project,
        all_services=True,
        unit_directory=tmp_path / "systemd",
    )

    assert {unit.key for unit in manager.units} == {"log-api", "api", "mcp"}
    assert callable(commands.log_publisher)
    assert all(unit.key != "logs" for unit in manager.units)
