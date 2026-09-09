from __future__ import annotations

from gway_web import clear, load_config, sites, url


def test_load_watchtower_config(tmp_path) -> None:
    config = tmp_path / "web.toml"
    config.write_text(
        """
[sites.watchtower]
domain = "gelectriic.com"
host = "127.0.0.1"
port = 8765
health_path = "/"
""".strip()
    )

    clear()
    loaded = load_config(str(config))

    assert [site.name for site in loaded] == ["watchtower"]
    assert url("watchtower") == "http://gelectriic.com"
    assert [site.name for site in sites()] == ["watchtower"]
