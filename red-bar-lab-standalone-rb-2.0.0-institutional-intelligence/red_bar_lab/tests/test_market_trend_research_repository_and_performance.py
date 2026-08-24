from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from time import perf_counter

from red_bar_lab.services.market_trend_research.calculator import DualPcrCalculator
from red_bar_lab.services.market_trend_research.models import (
    DualPcrResearchSnapshot,
    OptionOiCell,
    ResearchDataQuality,
    ResearchLatencyEvidence,
    ResearchState,
)
from red_bar_lab.services.market_trend_research.policy import MarketTrendResearchPolicy
from red_bar_lab.services.market_trend_research.repository import (
    MarketTrendResearchRepository,
)

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 8, 25)


def _cells(count_each_side: int = 251) -> tuple[OptionOiCell, ...]:
    rows = []
    middle = count_each_side // 2
    for index in range(count_each_side):
        strike = 24250.0 + (index - middle) * 50.0
        rows.append(
            OptionOiCell(
                f"NSE_FO|CE-{index}",
                "CE",
                strike,
                EXPIRY,
                1000.0 + index,
                900.0 + index,
                NOW,
            )
        )
        rows.append(
            OptionOiCell(
                f"NSE_FO|PE-{index}",
                "PE",
                strike,
                EXPIRY,
                1200.0 + index,
                1100.0 + index,
                NOW,
            )
        )
    return tuple(rows)


def _snapshot() -> DualPcrResearchSnapshot:
    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    cells = _cells(11)
    window = calculator.define_window(cells, spot=24250.0, window_steps=5)
    panel = calculator.panel(
        name="Current / Overall PCR",
        cells=cells,
        window=window,
        spot=24250.0,
        sessions_to_expiry=4,
        source_timestamp=NOW,
        evaluated_at=NOW,
    )
    return DualPcrResearchSnapshot(
        snapshot_id=DualPcrResearchSnapshot.build_id(
            underlying="NIFTY 50",
            provider="UPSTOX",
            source_timestamp=NOW,
        ),
        trading_date=NOW.date(),
        underlying="NIFTY 50",
        provider="UPSTOX",
        source_timestamp=NOW,
        evaluated_at=NOW,
        current_panel=panel,
        morning_panel=None,
        quality=ResearchDataQuality(
            ResearchState.MORNING_ANCHOR_UNAVAILABLE,
            0.0,
            ("MORNING_ANCHOR_UNAVAILABLE",),
        ),
        latency=ResearchLatencyEvidence(1.0, 1.0, 1.0, 1.0, 4.0),
        agreement_state="UNAVAILABLE",
        explanation=("Final market direction has not yet been calculated.",),
    )


def test_repository_isolated_atomic_projection_and_anchor(tmp_path):
    path = tmp_path / "research.db"
    repository = MarketTrendResearchRepository(path)
    snapshot = _snapshot()
    repository.persist(snapshot)
    projection = repository.latest_projection(underlying="NIFTY 50")
    assert projection is not None
    assert projection["authority"] == "OBSERVATIONAL_ONLY"
    assert projection["current_panel"]["rows"][-1]["strike"] == "OVERALL TOTAL"

    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    cells = _cells(11)
    window = calculator.define_window(cells, spot=24250.0, window_steps=5)
    assert repository.create_anchor(
        underlying="NIFTY 50",
        trading_date=NOW.date(),
        anchor_timestamp=NOW,
        spot=24250.0,
        window=window,
        cells=tuple(
            cell for cell in cells if cell.instrument_key in window.instrument_keys
        ),
    )
    assert not repository.create_anchor(
        underlying="NIFTY 50",
        trading_date=NOW.date(),
        anchor_timestamp=NOW + timedelta(minutes=1),
        spot=24300.0,
        window=window,
        cells=(),
    )
    restored = repository.load_anchor(
        underlying="NIFTY 50",
        trading_date=NOW.date(),
    )
    assert restored is not None
    assert restored["spot"] == 24250.0


def test_persistence_excludes_credentials_and_raw_payload(tmp_path):
    path = tmp_path / "research.db"
    repository = MarketTrendResearchRepository(path)
    repository.persist(_snapshot())
    data = path.read_bytes()
    assert b"Authorization" not in data
    assert b"Bearer " not in data
    assert b"raw_payload" not in data


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
        name="Current / Overall PCR",
        cells=cells,
        window=window,
        spot=24272.5,
        sessions_to_expiry=4,
        source_timestamp=NOW,
        evaluated_at=NOW,
    )
    calculation_ms = (perf_counter() - started) * 1000.0
    serialized_size = len(
        json.dumps(
            {
                "rows": panel.rows,
                "aggregate": panel.aggregate.pcr,
            },
            default=str,
        ).encode("utf-8")
    )
    assert len(cells) == 502
    assert len(index) == 502
    assert panel.observed_contract_count == 22
    assert normalization_ms < 500.0
    assert calculation_ms < 500.0
    assert serialized_size < 100_000
