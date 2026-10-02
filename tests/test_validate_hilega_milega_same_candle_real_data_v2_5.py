from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.validate_hilega_milega_same_candle_real_data_v2_5 import cross_up

IST = ZoneInfo("Asia/Kolkata")


def test_cross_up_true():
    assert cross_up(48.0, 50.0, 56.0, 51.0) is True


def test_cross_up_false_if_already_above():
    assert cross_up(52.0, 50.0, 53.0, 51.0) is False


def test_cross_up_false_if_not_above_current():
    assert cross_up(48.0, 50.0, 49.0, 51.0) is False
