from gway_web.dns import (
    DNSChallenge,
    challenge_name,
    cleanup,
    present,
    propagation_status,
    wait_for_propagation,
)


class FakeProvider:
    def __init__(self):
        self.records = {}
        self.calls = []

    def create_txt(self, name, value):
        self.calls.append(("create", name, value))
        self.records.setdefault(name, []).append(value)

    def remove_txt(self, name, value):
        self.calls.append(("remove", name, value))
        values = self.records.get(name, [])
        if value in values:
            values.remove(value)

    def txt_values(self, name):
        return tuple(self.records.get(name, ()))


def test_challenge_name_supports_normal_and_wildcard_domains():
    assert challenge_name("example.com") == "_acme-challenge.example.com"
    assert challenge_name("*.example.com") == "_acme-challenge.example.com"


def test_present_status_and_cleanup_use_provider_boundary():
    provider = FakeProvider()

    challenge = present(provider, "*.example.com", "proof")

    assert challenge == DNSChallenge(
        domain="*.example.com",
        name="_acme-challenge.example.com",
        value="proof",
    )
    assert propagation_status(provider, challenge).present is True

    cleanup(provider, challenge)

    assert provider.calls == [
        ("create", "_acme-challenge.example.com", "proof"),
        ("remove", "_acme-challenge.example.com", "proof"),
    ]
    assert propagation_status(provider, challenge).present is False


def test_wait_for_propagation_reports_attempts_without_provider_assumptions():
    class DelayedProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.reads = 0

        def txt_values(self, name):
            self.reads += 1
            if self.reads >= 3:
                return ("proof",)
            return ()

    provider = DelayedProvider()
    challenge = DNSChallenge("example.com", "_acme-challenge.example.com", "proof")
    ticks = iter((0.0, 0.0, 1.0, 2.0))

    result = wait_for_propagation(
        provider,
        challenge,
        timeout=10,
        interval=1,
        sleep_fn=lambda seconds: None,
        clock=lambda: next(ticks),
    )

    assert result.present is True
    assert result.attempts == 3
    assert result.observed_values == ("proof",)


def test_wait_for_propagation_returns_false_on_timeout():
    provider = FakeProvider()
    challenge = DNSChallenge("example.com", "_acme-challenge.example.com", "proof")
    ticks = iter((0.0, 0.0, 1.0))

    result = wait_for_propagation(
        provider,
        challenge,
        timeout=1,
        interval=1,
        sleep_fn=lambda seconds: None,
        clock=lambda: next(ticks),
    )

    assert result.present is False
    assert result.attempts == 2
