from __future__ import annotations

import importlib.util
from pathlib import Path

from gway.project import Project
from gway.service import ServiceManager

from gway_web import commands


def _project() -> Project:
    root = Path(__file__).resolve().parents[2]
    return Project.from_path(root)


def _service_keys(tmp_path: Path) -> set[str]:
    manager = ServiceManager(
        _project(),
        all_services=True,
        unit_directory=tmp_path / "systemd",
    )
    return {unit.key for unit in manager.units}


def test_web_services_exclude_removed_log_service(tmp_path: Path) -> None:
    assert _service_keys(tmp_path) == {"api", "mcp"}
    assert callable(commands.log_publisher)


def test_web_services_render_with_current_gway_service_model(tmp_path: Path) -> None:
    project = _project()

    api = ServiceManager(
        project,
        service="api",
        unit_directory=tmp_path / "systemd",
    )
    mcp = ServiceManager(
        project,
        service="mcp",
        unit_directory=tmp_path / "systemd",
    )

    api_unit = api.render(user="root")
    mcp_unit = mcp.render(user="root")

    assert api.unit_name == "gway-web-api.service"
    assert mcp.unit_name == "gway-web-mcp.service"
    assert "gway_web.api_service" in api_unit
    assert "gway_web.mcp_service" in mcp_unit
    assert "GWAY_CONFIG_HOME=" in api_unit
    assert "GWAY_DATA_HOME=" in api_unit
    assert "GWAY_CONFIG_HOME=" in mcp_unit
    assert "GWAY_DATA_HOME=" in mcp_unit


def test_removed_log_service_modules_stay_absent() -> None:
    assert importlib.util.find_spec("gway_web.log_service") is None
    assert importlib.util.find_spec("gway_web.logs") is None
