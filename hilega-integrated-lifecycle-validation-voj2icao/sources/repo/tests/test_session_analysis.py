from datetime import datetime, timedelta

import pytest

from market_lab.domain import ForwardLookupConfig, PCRHistoryRecord, PCRTrendConfig
from market_lab.session_analysis import build_session_analysis


AT = datetime.fromisoformat("2026-09-09T09:20:00+05:30")


def panel(observation_id: int, mode: str, minutes: int, spot: float, pcr: float) -> PCRHistoryRecord:
    timestamp = AT + timedelta(minutes=minutes)
    return PCRHistoryRecord(
        id=observation_id * 10 + {"fixed": 1, "moving": 2, "full": 3}[mode], observation_id=observation_id,
        configuration_version=1, record_kind="panel", mode=mode, fingerprint=f"{mode}-series",
        provider_timestamp=timestamp, received_at=timestamp, processed_at=timestamp, underlying_spot=spot,
        panel_pcr=pcr, data_status="AVAILABLE",
    )


def test_forward_targets_use_first_observation_at_or_after_target() -> None:
    records = [panel(index, mode, minute, 25_000 + minute, 1.0 + minute / 100) for index, minute in enumerate((0, 5, 10, 15, 30), 1) for mode in ("fixed", "moving", "full")]
    analysis = build_session_analysis(records, underlying="NIFTY", expiry=AT.date(), trend_config=PCRTrendConfig())
    first = analysis[0]
    assert first.spot_plus_5m == 25_005
    assert first.forward_change_15m == 15
    assert first.spot_plus_30m == 25_030


def test_missing_or_late_future_observations_remain_unavailable() -> None:
    records = [panel(1, mode, 0, 25_000, 1.0) for mode in ("fixed", "moving", "full")]
    records += [panel(2, mode, 6, 25_006, 1.1) for mode in ("fixed", "moving", "full")]
    analysis = build_session_analysis(records, underlying="NIFTY", expiry=AT.date(), trend_config=PCRTrendConfig(), forward_config=ForwardLookupConfig(timestamp_tolerance_seconds=30))
    assert analysis[0].spot_plus_5m is None
    assert analysis[0].forward_change_5m is None
    assert analysis[0].moving_trend_5m.value == "UNAVAILABLE"
