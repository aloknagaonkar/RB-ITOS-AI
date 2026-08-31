import logging

from red_bar_lab.brokers.upstox_client import ObservableRetry, UpstoxClient


def test_observable_retry_logs_safe_endpoint(caplog):
    retry = ObservableRetry(
        total=2,
        status=2,
        backoff_factor=0,
        status_forcelist=(503,),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )

    class Response:
        status = 503
        headers = {}

        def get_redirect_location(self):
            return None

    with caplog.at_level(logging.WARNING):
        retry.increment(
            method="GET",
            url="/v2/option/chain?instrument_key=secret",
            response=Response(),
        )

    text = caplog.text
    assert "broker_get_retry" in text
    assert "endpoint=/v2/option/chain" in text
    assert "instrument_key=secret" not in text
    assert "status=503" in text


def test_retry_policy_remains_idempotent_only():
    retry = ObservableRetry(
        total=3,
        status_forcelist=(503,),
        allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
    )

    assert retry.is_retry("GET", 503) is True
    assert retry.is_retry("POST", 503) is False


def test_upstox_client_retry_policy_tolerates_rate_limit_window():
    """Lock in the retry policy tuned for Upstox 429 rate-limit windows.

    Upstox free-tier rate-limit windows can last 20-60 seconds. The policy
    must allow enough cumulative wait time (total=5, backoff_factor=2.0
    -> 0s, 2s, 4s, 8s, 16s = 30s) to survive a typical window without
    collapsing the 429 into a terminal UpstoxAPIError.
    """
    client = UpstoxClient(access_token="token")
    policy = client.get_retry_policy

    assert policy["total"] == 5
    assert policy["backoff_factor"] == 2.0
    assert 429 in policy["status_forcelist"]
    assert policy["respect_retry_after_header"] is True
    assert set(policy["allowed_methods"]) == {"GET", "HEAD", "OPTIONS"}
