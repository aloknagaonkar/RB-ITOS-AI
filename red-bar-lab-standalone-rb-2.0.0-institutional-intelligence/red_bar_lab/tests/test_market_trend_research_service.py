from datetime import date, datetime, timedelta, timezone
import sqlite3

import pytest

from red_bar_lab.services.market_trend_research.models import OptionOiCell
from red_bar_lab.services.market_trend_research.policy import (
    MarketTrendResearchPolicy,
    StaticExchangeSessionCalendar,
)
from red_bar_lab.services.market_trend_research.repository import MarketTrendResearchRepository
from red_bar_lab.services.market_trend_research.service import MarketTrendResearchService
from red_bar_lab.services.market_trend_research.source import (
    NormalizedChainSnapshot,
    SourceReadResult,
)

REFERENCE_TIME = datetime(2026, 8, 24, 3, 38, 3, tzinfo=timezone.utc)
BASELINE_TIME = datetime(2026, 8, 24, 3, 45, 5, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 25)


def _chain(*, timestamp, spot=24250.0, ce=100.0, pe=125.0):
    cells = []
    for offset in range(-10, 11):
        strike = 24250.0 + offset * 50.0
        cells.append(
            OptionOiCell(
                f"CE-{strike}", "CE", strike, EXPIRY, ce, 90.0, timestamp
            )
        )
        cells.append(
            OptionOiCell(
                f"PE-{strike}", "PE", strike, EXPIRY, pe, 100.0, timestamp
            )
        )
    return NormalizedChainSnapshot(
        "NIFTY 50", "UPSTOX", timestamp, spot, EXPIRY, tuple(cells)
    )


class Source:
    def __init__(self, snapshots):
        self.snapshots = tuple(snapshots)
        self.calls = 0

    def recent_with_timings(self, *, underlying, limit=2):
        self.calls += 1
        assert underlying == "NIFTY 50"
        return SourceReadResult(self.snapshots[:limit], 1.0, 2.0)


def _service(tmp_path, source, policy=None, calendar=None):
    return MarketTrendResearchService(
        source=source,
        repository=MarketTrendResearchRepository(tmp_path / "research.db"),
        policy=policy or MarketTrendResearchPolicy(),
        calendar=calendar or StaticExchangeSessionCalendar(),
    )


def test_reference_then_oi_baseline_are_separate_immutable_stages(tmp_path):
    first = _service(tmp_path, Source((_chain(timestamp=REFERENCE_TIME),))).evaluate(
        underlying="NIFTY 50", evaluated_at=REFERENCE_TIME + timedelta(seconds=5)
    )
    assert first.lifecycle_state.value == "WAITING_FOR_OI_BASELINE"
    assert first.morning_reference is not None
    assert first.morning_reference.reference_timestamp == REFERENCE_TIME
    assert first.opening_oi_baseline is None
    assert first.morning_panel is None

    second = _service(tmp_path, Source((_chain(timestamp=BASELINE_TIME),))).evaluate(
        underlying="NIFTY 50", evaluated_at=BASELINE_TIME + timedelta(seconds=5)
    )
    assert second.lifecycle_state.value == "MORNING_RESEARCH_READY"
    assert second.morning_reference is not None
    assert second.morning_reference.reference_timestamp == REFERENCE_TIME
    assert second.opening_oi_baseline is not None
    assert second.opening_oi_baseline.baseline_timestamp == BASELINE_TIME
    assert second.morning_panel is not None
    assert second.morning_panel.rows[-1]["strike"] == "OVERALL TOTAL"


def test_reference_does_not_move_and_restart_restores_it(tmp_path):
    _service(
        tmp_path,
        Source((_chain(timestamp=REFERENCE_TIME, spot=24250.0),)),
    ).evaluate(
        underlying="NIFTY 50",
        evaluated_at=REFERENCE_TIME + timedelta(seconds=5),
    )
    later = REFERENCE_TIME + timedelta(minutes=2)
    snapshot = _service(
        tmp_path,
        Source((_chain(timestamp=later, spot=24400.0),)),
    ).evaluate(
        underlying="NIFTY 50",
        evaluated_at=later + timedelta(seconds=5),
    )
    assert snapshot.morning_reference is not None
    assert snapshot.morning_reference.reference_spot == 24250.0
    assert snapshot.morning_reference.fixed_atm == 24250.0


def test_baseline_does_not_move_and_current_oi_continues_updating(tmp_path):
    _service(tmp_path, Source((_chain(timestamp=REFERENCE_TIME),))).evaluate(
        underlying="NIFTY 50", evaluated_at=REFERENCE_TIME + timedelta(seconds=5)
    )
    _service(
        tmp_path,
        Source((_chain(timestamp=BASELINE_TIME, ce=100.0, pe=125.0),)),
    ).evaluate(
        underlying="NIFTY 50",
        evaluated_at=BASELINE_TIME + timedelta(seconds=5),
    )
    later = BASELINE_TIME + timedelta(minutes=10)
    snapshot = _service(
        tmp_path,
        Source((_chain(timestamp=later, spot=24500.0, ce=130.0, pe=150.0),)),
    ).evaluate(
        underlying="NIFTY 50",
        evaluated_at=later + timedelta(seconds=5),
    )
    assert snapshot.opening_oi_baseline is not None
    assert snapshot.opening_oi_baseline.baseline_timestamp == BASELINE_TIME
    assert snapshot.morning_panel is not None
    row = snapshot.morning_panel.rows[0]
    assert row["ce_opening_oi"] == 100.0
    assert row["ce_current_oi"] == 130.0
    assert row["ce_opening_change"] == 30.0


def test_no_reference_before_start_or_after_cutoff(tmp_path):
    too_early = REFERENCE_TIME - timedelta(minutes=1)
    early = _service(tmp_path, Source((_chain(timestamp=too_early),))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=too_early + timedelta(seconds=5),
    )
    assert early.morning_reference is None
    assert early.lifecycle_state.value == "WAITING_FOR_REFERENCE"

    late = datetime(2026, 8, 24, 3, 45, tzinfo=timezone.utc)
    late_snapshot = _service(
        tmp_path / "late",
        Source((_chain(timestamp=late),)),
    ).evaluate(
        underlying="NIFTY 50",
        evaluated_at=late + timedelta(seconds=5),
    )
    assert late_snapshot.morning_reference is None
    assert late_snapshot.quality.state.value == "MORNING_REFERENCE_UNAVAILABLE"


def test_partial_or_stale_snapshot_cannot_create_oi_baseline(tmp_path):
    _service(tmp_path, Source((_chain(timestamp=REFERENCE_TIME),))).evaluate(
        underlying="NIFTY 50", evaluated_at=REFERENCE_TIME + timedelta(seconds=5)
    )
    complete = _chain(timestamp=BASELINE_TIME)
    partial_cells = tuple(
        cell
        for cell in complete.cells
        if not (cell.strike == 24350.0 and cell.option_side == "PE")
    )
    partial = NormalizedChainSnapshot(
        complete.underlying,
        complete.provider,
        complete.source_timestamp,
        complete.spot,
        complete.expiry,
        partial_cells,
    )
    with pytest.raises(ValueError, match="PARTIAL_CONTRACT_WINDOW"):
        _service(tmp_path, Source((partial,))).evaluate(
            underlying="NIFTY 50",
            evaluated_at=BASELINE_TIME + timedelta(seconds=5),
        )

    stale_time = BASELINE_TIME + timedelta(minutes=2)
    stale = _service(
        tmp_path / "stale",
        Source((_chain(timestamp=REFERENCE_TIME),)),
    ).evaluate(underlying="NIFTY 50", evaluated_at=stale_time)
    assert stale.opening_oi_baseline is None


def test_previous_snapshot_from_prior_ist_day_is_not_compared(tmp_path):
    current_time = BASELINE_TIME + timedelta(days=1)
    current = _chain(timestamp=current_time, ce=110.0, pe=130.0)
    previous = _chain(timestamp=BASELINE_TIME, ce=100.0, pe=125.0)
    snapshot = _service(tmp_path, Source((current, previous))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=current_time + timedelta(seconds=5),
    )
    assert snapshot.current_panel.aggregate.previous_pcr is None
    assert (
        snapshot.current_panel.aggregate.persistence_state
        == "INSUFFICIENT_HISTORY"
    )


def test_current_window_transition_is_not_compared(tmp_path):
    current_time = BASELINE_TIME + timedelta(minutes=1)
    current = _chain(timestamp=current_time, spot=24300.0)
    previous = _chain(timestamp=BASELINE_TIME, spot=24250.0)
    snapshot = _service(tmp_path, Source((current, previous))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=current_time + timedelta(seconds=5),
    )
    assert snapshot.current_panel.state.value == "WINDOW_TRANSITION"
    assert (
        snapshot.current_panel.data_status
        == "Not comparable — ATM/window changed"
    )


def test_unverified_calendar_fails_closed(tmp_path):
    calendar = StaticExchangeSessionCalendar(
        source_name="UNVERIFIED",
        verified=False,
    )
    with pytest.raises(ValueError, match="SESSION_POSITION_UNAVAILABLE"):
        _service(
            tmp_path,
            Source((_chain(timestamp=REFERENCE_TIME),)),
            calendar=calendar,
        ).evaluate(
            underlying="NIFTY 50",
            evaluated_at=REFERENCE_TIME + timedelta(seconds=5),
        )


def test_timeout_is_published_once_and_never_as_ready(tmp_path):
    policy = MarketTrendResearchPolicy(hard_deadline_seconds=0.000001)
    snapshot = _service(
        tmp_path,
        Source((_chain(timestamp=REFERENCE_TIME),)),
        policy,
    ).evaluate(
        underlying="NIFTY 50",
        evaluated_at=REFERENCE_TIME + timedelta(seconds=5),
    )
    assert snapshot.quality.state.value == "TIMEOUT"
    with sqlite3.connect(tmp_path / "research.db") as connection:
        rows = connection.execute(
            "SELECT state, COUNT(*) FROM "
            "market_trend_research_snapshots GROUP BY state"
        ).fetchall()
    assert rows == [("TIMEOUT", 1)]
