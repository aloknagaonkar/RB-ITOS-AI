from dataclasses import dataclass
from pathlib import Path

from red_bar_lab.services.option_participation_store import (
    persist_option_participation,
    read_latest_option_participation,
    summarize_option_participation,
)


@dataclass
class Summary:
    observed_at: str
    underlying_name: str = "NIFTY 50"
    spot_price: float = 24000.0
    atm_strike: float = 24000.0
    expiry: str = "2026-08-25"
    pcr_oi: float = 1.0
    underlying_rsi: float = 50.0
    ce_score: float = 60.0
    pe_score: float = 40.0
    recommended_side: str = "CE"
    recommended_direction: str = "BULLISH"
    grade: str = "MODERATE"
    reason: str = "TEST"
    authority: str = "OBSERVATIONAL_ONLY"
    rows: tuple[dict[str, object], ...] = ()


def _rows(multiplier: float):
    result = []
    for side in ("CE", "PE"):
        for rank in range(1, 3):
            result.append({
                "option_type": side,
                "distance_rank": rank,
                "tradingsymbol": f"{side}-{rank}",
                "strike": 24000 + rank * 50,
                "current_price": 50.0 * multiplier,
                "volume": 100.0 * multiplier,
                "contract_volume": 10.0 * multiplier,
                "oi": 200.0 * multiplier,
                "oi_change": 20.0 * multiplier,
            })
    return tuple(result)


def test_latest_summary_contains_total_changes_vs_previous_snapshot(tmp_path: Path):
    database = tmp_path / "test.sqlite"
    persist_option_participation(
        database,
        Summary(observed_at="2026-08-21T10:00:00+05:30", rows=_rows(1.0)),
    )
    persist_option_participation(
        database,
        Summary(observed_at="2026-08-21T10:05:00+05:30", rows=_rows(1.5)),
    )

    latest = read_latest_option_participation(database)
    summary = summarize_option_participation(latest)
    assert summary["ce_volume_change_pct"] == 50.0
    assert summary["pe_volume_change_pct"] == 50.0
    assert summary["ce_contracts_change_pct"] == 50.0
    assert summary["pe_oi_change_pct"] == 50.0
    assert summary["ce_oi_change_change_pct"] == 50.0
    assert latest[0]["previous_refresh_price"] == 50.0
    assert latest[0]["premium_change_from_previous_refresh_pct"] == 50.0
    assert latest[0]["previous_refresh_oi"] == 200.0
    assert latest[0]["oi_change_from_previous_refresh"] == 100.0
    assert latest[0]["volume_change_from_previous_refresh_pct"] == 50.0
