import pytest

from gway_web import Site, clear, get, register, sites, upstream_url, url


def setup_function() -> None:
    clear()


def test_site_urls_use_domain_for_public_url() -> None:
    site = Site(name="watchtower", domain="gelectriic.com", host="127.0.0.1", port=8000)
    assert url(site) == "http://gelectriic.com"
    assert upstream_url(site) == "http://127.0.0.1:8000"
    assert site.health_url == "http://127.0.0.1:8000/"


def test_registry_sorts_and_retrieves_sites() -> None:
    register(Site(name="zeta"))
    register(Site(name="alpha", port=8001))
    assert [site.name for site in sites()] == ["alpha", "zeta"]
    assert get("alpha").port == 8001


def test_duplicate_registration_requires_replace() -> None:
    register(Site(name="watchtower"))
    with pytest.raises(ValueError, match="already registered"):
        register(Site(name="watchtower", port=9000))


def test_invalid_site_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        Site(name="")
    with pytest.raises(ValueError):
        Site(name="bad-port", port=0)
    with pytest.raises(ValueError):
        Site(name="bad-scheme", scheme="ftp")
    with pytest.raises(ValueError):
        Site(name="bad-health", health_path="health")
