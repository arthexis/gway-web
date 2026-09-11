import pytest

from gway_web import Site, clear, get, register, site, sites, upstream_url, url


def setup_function() -> None:
    clear()


def test_site_urls_use_domain_for_public_url() -> None:
    target = Site(name="watchtower", domain="gelectriic.com", host="127.0.0.1", port=8000)
    assert url(target) == "http://gelectriic.com"
    assert upstream_url(target) == "http://127.0.0.1:8000"
    assert target.health_url == "http://127.0.0.1:8000/"


def test_tls_intent_is_independent_from_upstream_scheme() -> None:
    target = Site(
        name="arthexis",
        domain="charge.example.com",
        host="127.0.0.1",
        port=8888,
        scheme="http",
        tls=True,
    )

    assert target.upstream_url == "http://127.0.0.1:8888"
    assert target.url == "https://charge.example.com"
    assert target.public_scheme == "https"


def test_site_command_builds_portable_site() -> None:
    target = site(
        "arthexis",
        domain="example.com",
        host="127.0.0.1",
        port=9000,
        scheme="https",
        health_path="/health/",
        tls=True,
        redirect_http=False,
        tls_certificate="/certs/fullchain.pem",
        tls_certificate_key="/certs/privkey.pem",
    )

    assert target == Site(
        name="arthexis",
        domain="example.com",
        host="127.0.0.1",
        port=9000,
        scheme="https",
        health_path="/health/",
        tls=True,
        redirect_http=False,
        tls_certificate="/certs/fullchain.pem",
        tls_certificate_key="/certs/privkey.pem",
    )


def test_site_command_uses_site_defaults() -> None:
    assert site("arthexis") == Site(name="arthexis")


def test_tls_certificate_paths_are_a_pair() -> None:
    with pytest.raises(ValueError, match="must be provided together"):
        Site(name="arthexis", tls=True, tls_certificate="/certs/fullchain.pem")
    with pytest.raises(ValueError, match="require tls=True"):
        Site(
            name="arthexis",
            tls_certificate="/certs/fullchain.pem",
            tls_certificate_key="/certs/privkey.pem",
        )


def test_registry_sorts_and_retrieves_sites() -> None:
    register(Site(name="zeta"))
    register(Site(name="alpha", port=8001))
    assert [target.name for target in sites()] == ["alpha", "zeta"]
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
