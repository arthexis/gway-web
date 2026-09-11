import gway_web


def test_certbot_provider_commands_are_public():
    assert callable(gway_web.certbot_status)
    assert callable(gway_web.certbot_obtain)
    assert callable(gway_web.certbot_renew)
    assert callable(gway_web.certbot_challenge)
    assert callable(gway_web.discover_certbot)
