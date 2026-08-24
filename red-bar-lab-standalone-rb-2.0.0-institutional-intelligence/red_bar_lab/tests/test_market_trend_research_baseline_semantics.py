from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from red_bar_lab.services.market_trend_research.calculator import DualPcrCalculator
from red_bar_lab.services.market_trend_research.models import OptionOiCell
from red_bar_lab.services.market_trend_research.policy import MarketTrendResearchPolicy

NOW = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
PREVIOUS = NOW - timedelta(seconds=5)
EXPIRY = date(2026, 8, 25)


def _cells(
    *,
    ce_current: float = 120.0,
    pe_current: float = 150.0,
    ce_previous_day: float | None = 90.0,
    pe_previous_day: float | None = 100.0,
) -> tuple[OptionOiCell, ...]:
    rows: list[OptionOiCell] = []
    for offset in range(-1, 2):
        strike = 24250.0 + offset * 50.0
        rows.append(
            OptionOiCell(
                f"CE-{strike}",
                "CE",
                strike,
                EXPIRY,
                ce_current,
                ce_previous_day,
                NOW,
            )
        )
        rows.append(
            OptionOiCell(
                f"PE-{strike}",
                "PE",
                strike,
                EXPIRY,
                pe_current,
                pe_previous_day,
                NOW,
            )
        )
    return tuple(rows)


def _baseline(
    cells: tuple[OptionOiCell, ...],
    *,
    ce: float,
    pe: float,
    timestamp: datetime,
) -> dict[str, OptionOiCell]:
    result: dict[str, OptionOiCell] = {}
    for cell in cells:
        value = ce if cell.option_side == "CE" else pe
        result[cell.instrument_key] = OptionOiCell(
            cell.instrument_key,
            cell.option_side,
            cell.strike,
            cell.expiry,
            value,
            cell.provider_prev_oi,
            timestamp,
        )
    return result


def _panel(
    *,
    cells: tuple[OptionOiCell, ...],
    opening: dict[str, OptionOiCell] | None = None,
    refresh: dict[str, OptionOiCell] | None = None,
):
    calculator = DualPcrCalculator(MarketTrendResearchPolicy())
    window = calculator.define_window(cells, spot=24250.0, window_steps=1)
    return calculator.panel(
        name="Current/Overall PCR",
        cells=cells,
        window=window,
        spot=24250.0,
        sessions_to_expiry=1,
        source_timestamp=NOW,
        evaluated_at=NOW,
        previous_by_key=refresh,
        opening_by_key=opening,
        previous_pcr=1.0 if refresh else None,
        previous_timestamp=PREVIOUS if refresh else None,
    )


def test_previous_day_opening_and_refresh_are_explicit_and_independent():
    cells = _cells()
    opening = _baseline(cells, ce=100.0, pe=130.0, timestamp=PREVIOUS)
    refresh = _baseline(cells, ce=119.0, pe=149.0, timestamp=PREVIOUS)
    row = _panel(cells=cells, opening=opening, refresh=refresh).rows[0]

    assert row["ce_previous_day_oi"] == 90.0
    assert row["ce_previous_day_change"] == 30.0
    assert row["ce_opening_oi"] == 100.0
    assert row["ce_opening_change"] == 20.0
    assert row["ce_previous_refresh_oi"] == 119.0
    assert row["ce_previous_refresh_change"] == 1.0

    assert row["pe_previous_day_oi"] == 100.0
    assert row["pe_previous_day_change"] == 50.0
    assert row["pe_opening_oi"] == 130.0
    assert row["pe_opening_change"] == 20.0
    assert row["pe_previous_refresh_oi"] == 149.0
    assert row["pe_previous_refresh_change"] == 1.0


def test_previous_refresh_never_replaces_previous_day_baseline():
    cells = _cells(ce_previous_day=80.0, pe_previous_day=110.0)
    refresh = _baseline(cells, ce=120.0, pe=150.0, timestamp=PREVIOUS)
    row = _panel(cells=cells, refresh=refresh).rows[0]
    assert row["ce_previous_day_oi"] == 80.0
    assert row["ce_previous_refresh_oi"] == 120.0
    assert row["ce_previous_day_change"] == 40.0
    assert row["ce_previous_refresh_change"] == 0.0


def test_missing_and_zero_previous_day_baselines_remain_explicit():
    missing = _panel(
        cells=_cells(ce_previous_day=None, pe_previous_day=None)
    ).rows[0]
    assert missing["ce_previous_day_oi"] is None
    assert missing["ce_previous_day_change_reason"] == "BASELINE_MISSING"
    assert missing["ce_previous_day_change_pct"] is None

    zero = _panel(
        cells=_cells(ce_previous_day=0.0, pe_previous_day=0.0)
    ).rows[0]
    assert zero["ce_previous_day_change"] == 120.0
    assert zero["ce_previous_day_change_pct"] is None
    assert zero["ce_previous_day_change_reason"] == "ZERO_BASELINE"


def test_aggregate_percentages_use_aggregate_totals_not_percentage_average():
    cells = list(_cells())
    for index, cell in enumerate(cells):
        if cell.option_side == "CE":
            current = 100.0 if cell.strike == 24200.0 else 300.0
            previous = 50.0 if cell.strike == 24200.0 else 250.0
        else:
            current = 200.0
            previous = 100.0
        cells[index] = OptionOiCell(
            cell.instrument_key,
            cell.option_side,
            cell.strike,
            cell.expiry,
            current,
            previous,
            cell.source_timestamp,
        )
    total = _panel(cells=tuple(cells)).rows[-1]
    expected_ce_pct = (
        (total["ce_current_oi"] - total["ce_previous_day_oi"])
        / total["ce_previous_day_oi"]
        * 100.0
    )
    assert total["ce_previous_day_change_pct"] == expected_ce_pct


def test_partial_baseline_disables_aggregate_percentage():
    cells = list(_cells())
    first = cells[0]
    cells[0] = OptionOiCell(
        first.instrument_key,
        first.option_side,
        first.strike,
        first.expiry,
        first.current_oi,
        None,
        first.source_timestamp,
    )
    total = _panel(cells=tuple(cells)).rows[-1]
    assert total["ce_previous_day_oi"] is None
    assert total["ce_previous_day_change_pct"] is None
    assert total["ce_previous_day_change_reason"] == "BASELINE_MISSING"


def test_ui_contract_names_primary_baselines_and_refresh_diagnostics_only():
    source = Path(
        "red_bar_lab/ui/market_trend_research_panel.py"
    ).read_text(encoding="utf-8")
    assert source.index("Morning Fixed-Level PCR") < source.index(
        "Current/Overall PCR"
    )
    assert "CE opening OI" in source
    assert "PE opening OI" in source
    assert "CE previous-day OI" in source
    assert "PE previous-day OI" in source
    assert "Short-term OI movement since previous refresh" in source
    assert "This compares adjacent collector snapshots" in source
    assert "STALE DATA" in source
    assert "Not available" in source
    assert "Upstox" not in source
    assert "requests" not in source


def test_ui_indian_and_signed_formatting_contract():
    from red_bar_lab.ui.market_trend_research_panel import (
        _indian,
        _percent,
        _signed,
    )

    assert _indian(1071525000) == "1,07,15,25,000"
    assert _signed(1200) == "+1,200"
    assert _signed(-1200) == "−1,200"
    assert _signed(0) == "0"
    assert _percent(12.345) == "+12.35%"
    assert _percent(-12.345) == "−12.35%"
    assert _percent(None) == "Not available"
