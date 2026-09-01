import time

from red_bar_lab.brokers.upstox_client import (
    GetPacer,
    _PacedSessionProxy,
    _env_float,
)


class _RecordingPacer:
    def __init__(self):
        self.waits = 0

    def wait(self):
        self.waits += 1
        return 0.0


class _FakeSession:
    def __init__(self):
        self.calls = []
        self.mounted = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return "get-response"

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return "post-response"

    def mount(self, prefix, adapter):
        self.mounted.append((prefix, adapter))


def test_pacer_first_call_does_not_wait():
    pacer = GetPacer(minimum_gap_seconds=0.5, maximum_wait_seconds=5.0)
    started = time.monotonic()
    delay = pacer.wait()
    assert delay == 0.0
    assert time.monotonic() - started < 0.2


def test_pacer_enforces_minimum_gap_between_gets():
    pacer = GetPacer(minimum_gap_seconds=0.15, maximum_wait_seconds=5.0)
    pacer.wait()
    started = time.monotonic()
    delay = pacer.wait()
    elapsed = time.monotonic() - started
    assert delay >= 0.1
    assert elapsed >= 0.1


def test_pacer_caps_wait_at_maximum():
    pacer = GetPacer(minimum_gap_seconds=10.0, maximum_wait_seconds=0.05)
    pacer.wait()
    started = time.monotonic()
    delay = pacer.wait()
    elapsed = time.monotonic() - started
    assert delay <= 0.05 + 1e-9
    assert elapsed < 1.0


def test_pacer_disabled_when_gap_is_zero():
    pacer = GetPacer(minimum_gap_seconds=0.0, maximum_wait_seconds=5.0)
    started = time.monotonic()
    for _ in range(5):
        assert pacer.wait() == 0.0
    assert time.monotonic() - started < 0.2


def test_paced_proxy_paces_only_gets_and_delegates_everything_else():
    session = _FakeSession()
    pacer = _RecordingPacer()
    proxy = _PacedSessionProxy(session, pacer)

    assert proxy.get("https://example/quote") == "get-response"
    assert pacer.waits == 1

    assert proxy.post("https://example/order") == "post-response"
    assert pacer.waits == 1

    proxy.mount("https://", object())
    assert len(session.mounted) == 1

    assert session.calls == [
        ("GET", "https://example/quote"),
        ("POST", "https://example/order"),
    ]


def test_env_float_parses_and_falls_back(monkeypatch):
    monkeypatch.setenv("RB_TEST_FLOAT", "2.5")
    assert _env_float("RB_TEST_FLOAT", 1.0) == 2.5
    monkeypatch.setenv("RB_TEST_FLOAT", "not-a-number")
    assert _env_float("RB_TEST_FLOAT", 1.0) == 1.0
    monkeypatch.delenv("RB_TEST_FLOAT", raising=False)
    assert _env_float("RB_TEST_FLOAT", 1.0) == 1.0
