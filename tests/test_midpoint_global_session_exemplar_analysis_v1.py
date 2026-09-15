from datetime import datetime

from market_lab.midpoint_global_session_exemplar_analysis_v1 import (
    latest_completed_5m,
    metric,
    quality_bucket,
)


def test_latest_completed_5m():
    t = datetime.fromisoformat("2026-09-15T09:28:00+05:30")
    assert latest_completed_5m(t).isoformat() == "2026-09-15T09:25:00+05:30"


def test_metric():
    x = metric([2.0, -1.0, 3.0])
    assert x["count"] == 3
    assert x["positive_count"] == 2
    assert x["profit_factor"] == 5.0


def test_quality_bucket_excellent():
    r = {"option_economics": {"net_5m_pct": 12.0}}
    assert quality_bucket(r) == "EXCELLENT_5M_GE_10"


def test_quality_bucket_large_loss():
    r = {"option_economics": {"net_5m_pct": -7.0}}
    assert quality_bucket(r) == "LARGE_LOSS_5M_LE_MINUS5"
