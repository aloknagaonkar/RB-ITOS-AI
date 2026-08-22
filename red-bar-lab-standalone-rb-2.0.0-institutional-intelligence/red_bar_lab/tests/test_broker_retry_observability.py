import logging

from red_bar_lab.runtime_hardening import ObservableRetry


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
        allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
    )

    assert retry.is_retry("GET", 503) is True
    assert retry.is_retry("POST", 503) is False
