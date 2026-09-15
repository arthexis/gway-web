from __future__ import annotations

import pytest

from gway_web.api_service import _loopback_host


def test_managed_api_accepts_loopback_bindings():
    assert _loopback_host("127.0.0.1") == "127.0.0.1"
    assert _loopback_host("::1") == "::1"
    assert _loopback_host("localhost") == "localhost"


@pytest.mark.parametrize("host", ["", "0.0.0.0", "::", "192.0.2.10"])
def test_managed_api_rejects_non_loopback_bindings(host):
    with pytest.raises(ValueError, match="loopback"):
        _loopback_host(host)
