from datetime import datetime

from market_lab.domain import IST
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
    STRATEGY_ID,
)


def test_strategy_id():
    assert STRATEGY_ID == "MIDPOINT_STRATEGY_SHADOW_V1"


def test_latest_complete_minute_is_strict():
    now = datetime(2026, 9, 29, 10, 5, 35, tzinfo=IST)
    latest = MidpointLiveShadowCoordinatorV1._latest_complete_minute(now)
    assert latest.hour == 10
    assert latest.minute == 4
    assert latest.second == 0
