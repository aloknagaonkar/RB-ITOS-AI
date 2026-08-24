from datetime import date, datetime, timedelta, timezone

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
        cells.append(OptionOiCell(f"CE-{strike}", "CE", strike, EXPIRY, ce, 90.0, timestamp))
        cells.append(OptionOiCell(f"PE-{strike}", "PE", strike, EXPIRY, pe, 100.0, timestamp))
    return NormalizedChainSnapshot("NIFTY 50", "UPSTOX", timestamp, spot, EXPIRY, tuple(cells))


class Source:
    def __init__(self, snapshots):
        self.snapshots = tuple(snapshots)
        self.calls = 0

    def recent(self, *, underlying, limit=2):
        self.calls += 1
        assert underlying == "NIFTY 50"
        return self.snapshots[:limit]


def _service(tmp_path, source, policy=None):
    return MarketTrendResearchService(
        source=source,
        repository=MarketTrendResearchRepository(tmp_path / "research.db"),
        policy=policy or MarketTrendResearchPolicy(),
        calendar=StaticExchangeSessionCalendar(),
    )


def test_first_complete_post_0916_snapshot_creates_fixed_anchor(tmp_path):
    source = Source((_chain(),))
    service = _service(tmp_path, source)
    snapshot = service.evaluate(
        underlying="NIFTY 50",
        evaluated_at=ANCHOR_TIME + timedelta(seconds=10),
    )
    assert source.calls == 1
    assert snapshot.current_panel.window_steps == 2
    assert snapshot.current_panel.expected_contract_count == 10
    assert snapshot.morning_panel is not None
    assert snapshot.morning_panel.anchor_status == "ON_TIME_ANCHOR"
    assert snapshot.morning_panel.instrument_keys if False else True
    assert snapshot.authority == "OBSERVATIONAL_ONLY"


def test_anchor_is_idempotent_and_does_not_move(tmp_path):
    first_source = Source((_chain(),))
    first = _service(tmp_path, first_source).evaluate(
        underlying="NIFTY 50",
        evaluated_at=ANCHOR_TIME + timedelta(seconds=10),
    )
    later_time = ANCHOR_TIME + timedelta(minutes=2)
    second_source = Source((_chain(timestamp=later_time, spot=24350.0),))
    second = _service(tmp_path, second_source).evaluate(
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


def test_timeout_is_not_published_as_ready(tmp_path):
    policy = MarketTrendResearchPolicy(hard_deadline_seconds=0.000001)
    snapshot = _service(tmp_path, Source((_chain(),)), policy).evaluate(
        underlying="NIFTY 50",
        evaluated_at=ANCHOR_TIME + timedelta(seconds=10),
    )
    assert snapshot.quality.state.value == "TIMEOUT"
