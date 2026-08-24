from datetime import date, datetime, timezone
import json
from time import perf_counter

from red_bar_lab.services.market_trend_research.calculator import DualPcrCalculator
from red_bar_lab.services.market_trend_research.models import (
    DualPcrResearchSnapshot,
    MorningReference,
    OpeningOiBaseline,
    OptionOiCell,
    ResearchDataQuality,
    ResearchLatencyEvidence,
    ResearchState,
)
from red_bar_lab.services.market_trend_research.policy import MarketTrendResearchPolicy
from red_bar_lab.services.market_trend_research.repository import MarketTrendResearchRepository

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 25)


def _cells(count_each_side: int = 251) -> tuple[OptionOiCell, ...]:
    rows = []
    middle = count_each_side // 2
    for index in range(count_each_side):
        strike = 24250.0 + (index - middle) * 50.0
        rows.append(OptionOiCell(f"NSE_FO|CE-{index}", "CE", strike, EXPIRY, 1000.0 + index, 900.0 + index, NOW))
        rows.append(OptionOiCell(f"NSE_FO|PE-{index}", "PE", strike, EXPIRY, 1200.0 + index, 1100.0 + index, NOW))
    return tuple(rows)


def _snapshot() -> DualPcrResearchSnapshot:
    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    cells = _cells(11)
    window = calculator.define_window(cells, spot=24250.0, window_steps=5)
    panel = calculator.panel(
        name="Current/Overall PCR",
        cells=cells,
        window=window,
        spot=24250.0,
        sessions_to_expiry=4,
        source_timestamp=NOW,
        evaluated_at=NOW,
    )
    return DualPcrResearchSnapshot(
        snapshot_id=DualPcrResearchSnapshot.build_id(
            underlying="NIFTY 50", provider="UPSTOX", source_timestamp=NOW
        ),
        trading_date=NOW.date(),
        underlying="NIFTY 50",
        provider="UPSTOX",
        source_timestamp=NOW,
        evaluated_at=NOW,
        current_panel=panel,
        morning_panel=None,
        quality=ResearchDataQuality(
            ResearchState.MORNING_REFERENCE_UNAVAILABLE,
            0.0,
            ("MORNING_REFERENCE_UNAVAILABLE",),
        ),
        latency=ResearchLatencyEvidence(1.0, 1.0, 1.0, 1.0, 4.0),
        agreement_state="UNAVAILABLE",
        explanation=("Final market direction has not yet been calculated.",),
        calendar_source="TEST_VERIFIED_CALENDAR",
    )


def test_repository_persists_projection_reference_baseline_source_and_health(tmp_path):
    path = tmp_path / "research.db"
    repository = MarketTrendResearchRepository(path)
    repository.persist(_snapshot())
    projection = repository.latest_projection(underlying="NIFTY 50")
    assert projection is not None
    assert projection["authority"] == "OBSERVATIONAL_ONLY"
    assert projection["current_panel"]["rows"][-1]["strike"] == "OVERALL TOTAL"

    reference = MorningReference(
        NOW.date(), "NIFTY 50", 24250.0, NOW, EXPIRY, 50.0, 24250.0, 2,
        (24150.0, 24200.0, 24250.0, 24300.0, 24350.0),
        "UPSTOX", 0.0, "REFERENCE_FIXED",
    )
    assert repository.create_reference(reference)
    assert not repository.create_reference(reference)
    restored_reference = repository.load_reference(
        underlying="NIFTY 50", trading_date=NOW.date()
    )
    assert restored_reference["reference_spot"] == 24250.0

    baseline_cells = tuple(cell for cell in _cells(11) if 24150.0 <= cell.strike <= 24350.0)
    baseline = OpeningOiBaseline(
        NOW.date(), "NIFTY 50", NOW, EXPIRY, baseline_cells, "OI_BASELINE_FIXED"
    )
    assert repository.create_oi_baseline(baseline)
    assert not repository.create_oi_baseline(baseline)
    assert repository.load_oi_baseline(
        underlying="NIFTY 50", trading_date=NOW.date()
    )["status"] == "OI_BASELINE_FIXED"

    repository.persist_source_snapshot(
        snapshot_key="source-1",
        underlying="NIFTY 50",
        trading_date=NOW.date(),
        source_timestamp=NOW,
        expiry=EXPIRY,
        provider="UPSTOX",
        spot=24250.0,
        cells=baseline_cells,
        request_ms=100.0,
        normalization_ms=2.0,
    )
    assert len(repository.recent_source_payloads(underlying="NIFTY 50")) == 1

    repository.persist_runtime_health(
        runtime_name="MARKET_TREND_RESEARCH",
        heartbeat_at=NOW,
        last_success_at=NOW,
        last_failure_at=None,
        last_failure_reason=None,
        consecutive_failures=0,
        dropped_obsolete_tasks=2,
    )
    assert repository.latest_runtime_health()["dropped_obsolete_tasks"] == 2


def test_persistence_excludes_credentials_and_raw_payload(tmp_path):
    path = tmp_path / "research.db"
    repository = MarketTrendResearchRepository(path)
    repository.persist(_snapshot())
    data = path.read_bytes()
    assert b"Authorization" not in data
    assert b"Bearer " not in data
    assert b"raw_payload" not in data
    assert b"access_token" not in data


def test_realistic_chain_cpu_benchmark_is_bounded():
    policy = MarketTrendResearchPolicy()
    calculator = DualPcrCalculator(policy)
    cells = _cells(251)
    started = perf_counter()
    index = calculator.index(cells)
    normalization_ms = (perf_counter() - started) * 1000.0
    started = perf_counter()
    window = calculator.define_window(cells, spot=24272.5, window_steps=5)
    panel = calculator.panel(
        name="Current/Overall PCR",
        cells=cells,
        window=window,
        spot=24272.5,
        sessions_to_expiry=4,
        source_timestamp=NOW,
        evaluated_at=NOW,
    )
    calculation_ms = (perf_counter() - started) * 1000.0
    serialized_size = len(json.dumps({"rows": panel.rows, "pcr": panel.aggregate.pcr}, default=str).encode())
    assert len(cells) == 502
    assert len(index) == 502
    assert panel.observed_contract_count == 22
    assert normalization_ms < 500.0
    assert calculation_ms < 500.0
    assert serialized_size < 100_000
