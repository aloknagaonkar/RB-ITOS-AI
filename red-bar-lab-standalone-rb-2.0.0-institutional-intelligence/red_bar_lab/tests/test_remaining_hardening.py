from __future__ import annotations

import inspect

import requests

from red_bar_lab.brokers.upstox_client import UpstoxClient
from red_bar_lab.ui.pages import market_readiness


def test_upstox_get_retry_policy_is_bounded_and_get_only():
    client = UpstoxClient("token", session=requests.Session())
    policy = client.get_retry_policy

    assert policy["total"] == 3
    assert policy["backoff_factor"] == 0.5
    assert policy["status_forcelist"] == (429, 502, 503, 504)
    assert "GET" in policy["allowed_methods"]
    assert "POST" not in policy["allowed_methods"]
    assert policy["respect_retry_after_header"] is True
    assert policy["observability"] == "broker_get_retry"


def test_legacy_tab_no_longer_executes_independent_recommendation():
    source = inspect.getsource(market_readiness.render_page)

    assert "Legacy Full Trade Evidence" in source
    assert "Live legacy recommendation recalculation is disabled" in source
    assert "render_legacy_page(" not in source


def test_package_import_has_no_runtime_monkey_patch_side_effects():
    import red_bar_lab

    source = inspect.getsource(red_bar_lab)
    assert "runtime_hardening" not in source
    assert "install(" not in source
    assert "monkey-patch" in source
