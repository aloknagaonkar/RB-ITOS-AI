from datetime import date, datetime, timedelta, timezone
import sqlite3

import pytest

from red_bar_lab.services.market_trend_research.models import OptionOiCell
from red_bar_lab.services.market_trend_research.policy import (
    MarketTrendResearchPolicy,
    StaticExchangeSessionCalendar,
)
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)
from red_bar_lab.services.market_trend_research.service import (
    MarketTrendResearchService,
)
from red_bar_lab.services.market_trend_research.source import (
    NormalizedChainSnapshot,
)

ANCHOR_TIME = datetime(2026, 8, 24, 3, 46, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 25)


def _chain(*, timestamp=ANCHOR_TIME, spot=24250.0, ce=100.0, pe=125.0):
    cells = []
    for offset in range(-5, 6):
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
        "NIFTY 50",
        "UPSTOX",
        timestamp,
        spot,
        EXPIRY,
        tuple(cells),
    )


class Source:
    def __init__(self, snapshots):
        self.snapshots = tuple(snapshots)
        self.calls = 0

    def recent(self, *, underlying, limit=2):
        self.calls += 1
        assert underlying == "NIFTY 50"
        return self.snapshots[:limit]


def _service(tmp_path, source, policy=None, calendar=None):
    return MarketTrendResearchService(
        source=source,
        repository=MarketTrendResearchRepository(tmp_path / "research.db"),
        policy=policy or MarketTrendResearchPolicy(),
        calendar=calendar or StaticExchangeSessionCalendar(),
    )


def test_first_complete_post_0916_snapshot_creates_fixed_anchor(tmp_path):
    source = Source((_chain(),))
    snapshot = _service(tmp_path, source).evaluate(
        underlying="NIFTY 50",
        evaluated_at=ANCHOR_TIME + timedelta(seconds=10),
    )
    assert source.calls == 1
    assert snapshot.current_panel.window_steps == 2
    assert snapshot.current_panel.expected_contract_count == 10
    assert snapshot.morning_panel is not None
    assert snapshot.morning_panel.anchor_status == "ON_TIME_ANCHOR"
    assert snapshot.morning_panel.expected_contract_count == 10
    assert snapshot.morning_panel.rows[-1]["strike"] == "OVERALL TOTAL"
    assert snapshot.authority == "OBSERVATIONAL_ONLY"


def test_anchor_one_second_after_cutoff_is_on_time(tmp_path):
    timestamp = ANCHOR_TIME + timedelta(seconds=1)
    snapshot = _service(tmp_path, Source((_chain(timestamp=timestamp),))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=timestamp + timedelta(seconds=5),
    )
    assert snapshot.morning_panel is not None
    assert snapshot.morning_panel.anchor_status == "ON_TIME_ANCHOR"


def test_anchor_is_idempotent_and_does_not_move(tmp_path):
    first = _service(tmp_path, Source((_chain(),))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=ANCHOR_TIME + timedelta(seconds=10),
    )
    later_time = ANCHOR_TIME + timedelta(minutes=2)
    second = _service(
        tmp_path,
        Source((_chain(timestamp=later_time, spot=24350.0),)),
    ).evaluate(
        underlying="NIFTY 50",
        evaluated_at=later_time + timedelta(seconds=10),
    )
    assert first.morning_panel is not None
    assert second.morning_panel is not None
    assert second.morning_panel.anchor_timestamp == first.morning_panel.anchor_timestamp
    assert second.morning_panel.anchor_spot == first.morning_panel.anchor_spot
    assert second.current_panel.atm != second.morning_panel.atm


def test_late_snapshot_does_not_retroactively_invent_anchor(tmp_path):
    late = ANCHOR_TIME + timedelta(minutes=10)
    snapshot = _service(tmp_path, Source((_chain(timestamp=late),))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=late + timedelta(seconds=10),
    )
    assert snapshot.morning_panel is None
    assert snapshot.quality.state.value == "MORNING_ANCHOR_UNAVAILABLE"


def test_current_window_transition_blocks_unlike_pcr_comparison(tmp_path):
    current_time = ANCHOR_TIME + timedelta(minutes=1)
    current = _chain(timestamp=current_time, spot=24300.0, ce=110.0, pe=130.0)
    previous = _chain(timestamp=ANCHOR_TIME, spot=24250.0)
    snapshot = _service(tmp_path, Source((current, previous))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=current_time + timedelta(seconds=10),
    )
    assert snapshot.current_panel.state.value == "WINDOW_TRANSITION"
    assert snapshot.current_panel.aggregate.previous_pcr is None


def test_previous_snapshot_from_prior_ist_day_is_not_compared(tmp_path):
    current_time = ANCHOR_TIME + timedelta(days=1)
    current = _chain(timestamp=current_time, ce=110.0, pe=130.0)
    previous = _chain(timestamp=ANCHOR_TIME, ce=100.0, pe=125.0)
    snapshot = _service(tmp_path, Source((current, previous))).evaluate(
        underlying="NIFTY 50",
        evaluated_at=current_time + timedelta(seconds=10),
    )
    assert snapshot.current_panel.aggregate.previous_pcr is None
    assert snapshot.current_panel.aggregate.absolute_change is None
    assert snapshot.current_panel.aggregate.persistence_state == "INSUFFICIENT_HISTORY"
    strike_row = snapshot.current_panel.rows[0]
    assert strike_row["ce_baseline_oi"] is None
    assert strike_row["pe_baseline_oi"] is None


def test_unverified_calendar_fails_closed(tmp_path):
    calendar = StaticExchangeSessionCalendar(
        source_name="UNVERIFIED_WEEKDAY_ONLY",
        verified=False,
    )
    with pytest.raises(ValueError, match="SESSION_POSITION_UNAVAILABLE"):
        _service(tmp_path, Source((_chain(),)), calendar=calendar).evaluate(
            underlying="NIFTY 50",
            evaluated_at=ANCHOR_TIME + timedelta(seconds=10),
        )


def test_timeout_is_published_once_and_never_as_ready(tmp_path):
    policy = MarketTrendResearchPolicy(hard_deadline_seconds=0.000001)
    snapshot = _service(tmp_path, Source((_chain(),)), policy).evaluate(
        underlying="NIFTY 50",
        evaluated_at=ANCHOR_TIME + timedelta(seconds=10),
    )
    assert snapshot.quality.state.value == "TIMEOUT"
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT state, COUNT(*) FROM market_trend_research_snapshots GROUP BY state"
        ).fetchall()
    assert rows == [("TIMEOUT", 1)]
    assert snapshot.latency.persistence_ms >= 0.0
    assert snapshot.latency.end_to_end_ms >= snapshot.latency.calculation_ms
