from __future__ import annotations

from gway_web import clear, health, load_config, sites, status, url


def test_load_watchtower_config(tmp_path, monkeypatch) -> None:
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

    monkeypatch.setattr("gway_web.health.socket.create_connection", lambda *args, **kwargs: _Conn())
    assert status("watchtower") is True


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
