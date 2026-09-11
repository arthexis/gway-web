from pathlib import Path
import tomllib

import gway_web


def test_package_has_version() -> None:
    assert gway_web.__version__


def test_gway_manifest_exports_web_package() -> None:
    manifest = tomllib.loads(Path("gway.toml").read_text(encoding="utf-8"))

    assert manifest["project"]["name"] == "web"
    assert "gway-web" in manifest["project"]["aliases"]
    assert manifest["adapter"] == {"type": "python", "module": "gway_web"}
