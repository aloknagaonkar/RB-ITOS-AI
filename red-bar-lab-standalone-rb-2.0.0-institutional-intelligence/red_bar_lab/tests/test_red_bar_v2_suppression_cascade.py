"""Regressions for the three defects that jointly suppressed RB V2 entries.

Observed live on 2026-09-02: the UI reported
``RSI_HISTORY_INSUFFICIENT · V2_SNAPSHOT_STALE · Global readiness has
blocking market-data gaps`` while every market-data feed was READY.

1. The monitored replay copied a *per-bar* evaluation health onto the
   *session* data-source health, so the 5M Wilder RSI warm-up window
   (RSI(14) needs 15 completed 5M bars, i.e. 10:30 IST) read as a
   session-wide data-source outage for 99 consecutive cycles.
2. ``assess_global_readiness`` asserted "blocking market-data gaps" for any
   blocker, including a V2-alignment-only block.
3. The paper bridge's freshness window ``evaluation <= recorded <= current``
   could never hold, because ``recorded_at`` is stamped after the caller
   captured ``now``. Freshness silently fell back to the admission candle,
   which does not advance while a direction persists, so the bridge blocked
   with ``V2_SNAPSHOT_STALE`` for the rest of the session.
"""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.paper_strategy_authority import PaperStrategyAuthority
from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2VwapSourceHealth,
)
from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.services import red_bar_v2_futures_replay_service as service
from red_bar_lab.services.global_readiness import (
    BLOCKED,
    READY,
    UNAVAILABLE,
    assess_global_readiness,
)
from red_bar_lab.services.red_bar_v2_historical_replay import (
    RedBarV2ReplayResult,
    ReplayEvent,
)
from red_bar_lab.services.red_bar_v2_paper_signal_bridge import (
    MAXIMUM_RECORDED_FORWARD_SKEW_SECONDS,
    validate_snapshot_for_paper,
)

IST = "Asia/Kolkata"
IST_TZ = ZoneInfo(IST)


class _StubDatabase:
    """The service's PCR reader only touches ``.path``; ``None`` short-circuits."""

    path = None


def _candles(periods: int) -> pd.DataFrame:
    timestamps = pd.date_range(
        "2026-09-02 09:15", periods=periods, freq="1min", tz=IST
    )
    return pd.DataFrame(
        {
            "open": [100.0] * periods,
            "high": [101.0] * periods,
            "low": [99.0] * periods,
            "close": [100.0] * periods,
            "volume": [1000.0] * periods,
        },
        index=pd.Index(timestamps, name="timestamp"),
    )


def _evaluation_health(status: str, reason: str) -> RedBarV2VwapSourceHealth:
    stamp = datetime(2026, 9, 2, 10, 15, tzinfo=timezone.utc)
    return RedBarV2VwapSourceHealth(
        status=status,
        reason=reason,
        price_source_instrument="NIFTY",
        rsi_source_instrument="NIFTY",
        vwap_source_instrument="NIFTY-FUT",
        timeframe="5M",
        index_rows=14,
        futures_rows=14,
        aligned_rows=14,
        alignment_coverage_pct=100.0,
        positive_volume_rows=14,
        index_timestamp=stamp,
        futures_timestamp=stamp,
        last_aligned_timestamp=stamp,
    )


def _replay() -> RedBarV2ReplayResult:
    stamp = pd.Timestamp("2026-09-02 09:34", tz=IST)
    return RedBarV2ReplayResult(
        instrument_key="NIFTY",
        trading_date="2026-09-02",
        reference_timestamp=pd.Timestamp("2026-09-02 09:20", tz=IST),
        reference_midpoint=100.0,
        events=(
            ReplayEvent(
                timestamp=stamp,
                event_type="CANDIDATE_ADMISSION",
                direction="BULLISH",
                option_side="CE",
                admission_code="INITIAL_BULLISH_ALIGNMENT",
                candidate_allowed=True,
                trade_id=None,
                details={},
            ),
        ),
        admitted_candidates=1,
        blocked_candidates=0,
        closed_trades=0,
        final_trade_state="FLAT",
    )


def _run(monkeypatch, tmp_path, *, evaluation_health, live_result=None):
    monkeypatch.setattr(
        service,
        "replay_red_bar_v2_day_with_futures_vwap",
        lambda *args, **kwargs: (_replay(), evaluation_health),
    )
    if live_result is not None:
        monkeypatch.setattr(
            service,
            "build_red_bar_v2_futures_snapshot",
            lambda *args, **kwargs: live_result,
        )
    return service.run_monitored_red_bar_v2_futures_replay(
        _candles(82),
        _candles(82),
        database=_StubDatabase(),
        instrument_key="NIFTY",
        vwap_instrument_key="NIFTY-FUT",
        artifacts_root=tmp_path,
    )


def _persisted_snapshot(tmp_path) -> dict:
    target = tmp_path / "operations" / "red_bar_v2_ui_snapshot.json"
    return json.loads(target.read_text(encoding="utf-8"))


def test_per_bar_rsi_warmup_does_not_become_a_session_data_source_outage(
    monkeypatch, tmp_path
) -> None:
    """Defect 1: the 5M RSI warm-up must not be reported as a session fault."""
    live = _evaluation_health("READY", "FULL_TIMESTAMP_ALIGNMENT")
    result = _run(
        monkeypatch,
        tmp_path,
        evaluation_health=_evaluation_health("BLOCKED", "RSI_HISTORY_INSUFFICIENT"),
        live_result=(None, live),
    )

    assert result.health.status == "READY"
    assert result.health.reason != "RSI_HISTORY_INSUFFICIENT"
    # The per-bar verdict is still available, as a separate diagnostic.
    assert result.evaluation_health is not None
    assert result.evaluation_health.reason == "RSI_HISTORY_INSUFFICIENT"


def test_session_health_still_reports_genuine_data_source_faults(
    monkeypatch, tmp_path
) -> None:
    """Removing the override must not hide a real session-wide gap."""
    result = _run(
        monkeypatch,
        tmp_path,
        evaluation_health=_evaluation_health("READY", "FULL_TIMESTAMP_ALIGNMENT"),
        live_result=(None, _evaluation_health("READY", "FULL_TIMESTAMP_ALIGNMENT")),
    )
    assert result.health.status == "READY"

    empty = pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"],
        index=pd.DatetimeIndex([], name="timestamp", tz=IST),
    )
    monkeypatch.setattr(
        service,
        "replay_red_bar_v2_day_with_futures_vwap",
        lambda *args, **kwargs: (
            _replay(),
            _evaluation_health("READY", "FULL_TIMESTAMP_ALIGNMENT"),
        ),
    )
    degraded = service.run_monitored_red_bar_v2_futures_replay(
        _candles(82),
        empty,
        database=_StubDatabase(),
        instrument_key="NIFTY",
        vwap_instrument_key="NIFTY-FUT",
        artifacts_root=tmp_path / "degraded",
    )
    assert degraded.health.status != "READY"
    assert "FUTURES" in degraded.health.reason


def test_unavailable_live_context_is_reported_not_masked(
    monkeypatch, tmp_path
) -> None:
    """A live 1M failure must reach ``alignment_status``.

    When no live context can be built the snapshot still carries the
    replay's last-event prices, which may be hours old. Leaving the session
    verdict in place would let the paper bridge publish against them.
    """
    result = _run(
        monkeypatch,
        tmp_path,
        evaluation_health=_evaluation_health("READY", "FULL_TIMESTAMP_ALIGNMENT"),
        live_result=(
            None,
            _evaluation_health("BLOCKED", "FUTURES_TIMESTAMP_MISMATCH"),
        ),
    )
    payload = _persisted_snapshot(tmp_path)

    assert result.health.status == "READY"
    assert payload["alignment_status"] == "BLOCKED"
    assert payload["session_completeness"] == "UNAVAILABLE"


def test_global_readiness_does_not_blame_market_data_for_alignment_blocks() -> None:
    """Defect 2: name the blocking dimension instead of guessing."""
    result = assess_global_readiness(
        underlying_candle=READY,
        option_chain=READY,
        option_quotes=READY,
        pcr=READY,
        futures=READY,
        futures_strength="STRONG",
        v2_alignment=BLOCKED,
    )

    assert result.status == BLOCKED
    assert result.blocking_reasons == ("V2_ALIGNMENT_BLOCKED",)
    assert "market-data gaps" not in result.reason
    assert "alignment" in result.reason.lower()
    assert BLOCKED in result.reason


def test_global_readiness_names_the_failing_data_dimensions() -> None:
    result = assess_global_readiness(
        underlying_candle=BLOCKED,
        option_chain=READY,
        option_quotes=READY,
        pcr="MISSING",
        futures=READY,
        v2_alignment=READY,
    )

    assert result.status == BLOCKED
    assert "market-data gaps" in result.reason
    assert "underlying candles" in result.reason
    assert "PCR" in result.reason
    assert "option chain" not in result.reason


def test_global_readiness_reports_both_causes_together() -> None:
    result = assess_global_readiness(
        underlying_candle=BLOCKED,
        option_chain=READY,
        option_quotes=READY,
        v2_alignment="MISALIGNED",
    )

    assert result.status == BLOCKED
    assert "underlying candles" in result.reason
    assert "MISALIGNED" in result.reason


def test_global_readiness_unavailable_only_path_is_unchanged() -> None:
    result = assess_global_readiness(
        underlying_candle=UNAVAILABLE,
        option_chain=READY,
        option_quotes=READY,
    )
    assert result.status == UNAVAILABLE
    assert "cannot be established" in result.reason


def _authority() -> PaperStrategyAuthority:
    return PaperStrategyAuthority(
        primary_red_bar_version="v2",
        red_bar_v2_enabled=True,
        red_bar_v2_mode="paper",
        legacy_red_bar_v1_enabled=False,
        dri_strategy_enabled=False,
        rsi_extreme_reversal_enabled=False,
        broker_execution_enabled=False,
    )


def _admitted_snapshot(*, recorded_at: str | None) -> RedBarV2UISnapshot:
    return RedBarV2UISnapshot(
        correlation_id="RBV2-RUNTIME",
        alignment_status="READY",
        admission_allowed=True,
        admission_code="INITIAL_BULLISH_ALIGNMENT",
        direction="BULLISH",
        option_side="CE",
        # The admission candle. It does not advance while the direction
        # persists, which is exactly why it is unfit as a freshness anchor.
        admission_timestamp="2026-09-02T09:34:00+05:30",
        reference_timestamp="2026-09-02T09:20:00+05:30",
        index_close=23843.25,
        recorded_at=recorded_at,
    )


def test_snapshot_written_after_now_was_captured_is_fresh() -> None:
    """Defect 3: the caller's ``now`` predates the snapshot write.

    ``paper_monitor`` captures ``cycle_started`` at the top of the cycle and
    only reaches the bridge once the replay has persisted the snapshot, so
    ``recorded_at`` always reads slightly ahead of ``now``. That is healthy;
    it must not fall back to the frozen admission candle.
    """
    now = datetime(2026, 9, 2, 10, 37, 0, tzinfo=IST_TZ)
    snapshot = _admitted_snapshot(
        recorded_at=(now + timedelta(seconds=8)).isoformat()
    )

    result = validate_snapshot_for_paper(snapshot, authority=_authority(), now=now)

    assert result.status == "READY"
    assert result.reason == "V2_PAPER_SIGNAL_READY"


def test_hours_old_admission_with_a_current_snapshot_is_not_stale() -> None:
    """The exact live failure: READY context, admission at 09:34, blocked all day."""
    now = datetime(2026, 9, 2, 12, 45, 0, tzinfo=IST_TZ)
    snapshot = _admitted_snapshot(
        recorded_at=(now + timedelta(seconds=3)).isoformat()
    )

    result = validate_snapshot_for_paper(snapshot, authority=_authority(), now=now)

    assert result.status == "READY", "freshness must follow the artifact write time"


def test_genuinely_stale_snapshot_still_blocks() -> None:
    now = datetime(2026, 9, 2, 12, 45, 0, tzinfo=IST_TZ)
    snapshot = _admitted_snapshot(
        recorded_at=(now - timedelta(seconds=400)).isoformat()
    )

    result = validate_snapshot_for_paper(snapshot, authority=_authority(), now=now)

    assert result.status == "BLOCKED"
    assert result.reason == "V2_SNAPSHOT_STALE"


def test_recorded_at_beyond_the_skew_allowance_is_not_trusted() -> None:
    """A wildly future ``recorded_at`` means an untrustworthy clock."""
    now = datetime(2026, 9, 2, 12, 45, 0, tzinfo=IST_TZ)
    snapshot = _admitted_snapshot(
        recorded_at=(
            now + timedelta(seconds=MAXIMUM_RECORDED_FORWARD_SKEW_SECONDS + 60)
        ).isoformat()
    )

    result = validate_snapshot_for_paper(snapshot, authority=_authority(), now=now)

    assert result.status == "BLOCKED"
    assert result.reason == "V2_SNAPSHOT_STALE"


def test_missing_recorded_at_falls_back_to_the_admission_stamp() -> None:
    now = datetime(2026, 9, 2, 9, 35, 30, tzinfo=IST_TZ)
    fresh = validate_snapshot_for_paper(
        _admitted_snapshot(recorded_at=None), authority=_authority(), now=now
    )
    assert fresh.status == "READY"

    later = validate_snapshot_for_paper(
        _admitted_snapshot(recorded_at=None),
        authority=_authority(),
        now=datetime(2026, 9, 2, 10, 37, 0, tzinfo=IST_TZ),
    )
    assert later.status == "BLOCKED"
    assert later.reason == "V2_SNAPSHOT_STALE"
