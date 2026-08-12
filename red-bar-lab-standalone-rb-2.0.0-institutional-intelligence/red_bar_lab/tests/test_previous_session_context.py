from pathlib import Path

import pandas as pd

from red_bar_lab.intelligence.previous_session_context import PreviousSessionContextService


class _Database:
    def __init__(self, rows):
        self.rows = rows

    def read_option_chain_history(self, instrument_key, from_date, to_date, limit=5000):
        return list(self.rows)


def _write_chain(path: Path, *, pe_oi: float, pe_ltp: float, ce_oi: float = 800000, ce_ltp: float = 110):
    pd.DataFrame([
        {"spot": 24450, "strike": 24400, "call_ltp": ce_ltp, "put_ltp": pe_ltp, "call_oi": ce_oi, "put_oi": pe_oi, "call_volume": 900000, "put_volume": 1100000},
        {"spot": 24450, "strike": 24450, "call_ltp": 90, "put_ltp": 95, "call_oi": 600000, "put_oi": 1000000, "call_volume": 700000, "put_volume": 1300000},
        {"spot": 24450, "strike": 24500, "call_ltp": 70, "put_ltp": 120, "call_oi": 500000, "put_oi": 700000, "call_volume": 600000, "put_volume": 800000},
    ]).to_csv(path, index=False)


def _rows(tmp_path, mode="ONLINE"):
    first, last = tmp_path / f"{mode}-first.csv", tmp_path / f"{mode}-last.csv"
    _write_chain(first, pe_oi=1600000, pe_ltp=105)
    _write_chain(last, pe_oi=1200000, pe_ltp=85)
    return [
        {"collector_mode": mode, "snapshot_timestamp": "2026-08-11T15:20:00+05:30", "chain_artifact_path": str(first), "option_expiry": "2026-08-18"},
        {"collector_mode": mode, "snapshot_timestamp": "2026-08-11T15:29:00+05:30", "chain_artifact_path": str(last), "option_expiry": "2026-08-18"},
    ]


def test_previous_session_context_uses_last_completed_online_session(tmp_path):
    context = PreviousSessionContextService(_Database(_rows(tmp_path))).latest_before("NSE_INDEX|Nifty 50", "2026-08-12")
    assert context.status == "READY"
    assert context.previous_trading_date == "2026-08-11"
    assert context.snapshot_count == 2
    assert context.data_source == "ONLINE"
    assert context.closing_pcr is not None
    assert context.closing_max_pain is not None
    assert context.dominant_strike is not None
    assert context.dominant_side in {"CALL", "PUT"}
    assert context.carry_forward_bias in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert "opening expectation only" in context.opening_narrative
    assert context.execution_impact == "NONE"


def test_previous_session_context_falls_back_to_validated_historical_snapshots(tmp_path):
    context = PreviousSessionContextService(_Database(_rows(tmp_path, "HISTORICAL"))).latest_before("NSE_INDEX|Nifty 50", "2026-08-12")
    assert context.status == "READY"
    assert context.previous_trading_date == "2026-08-11"
    assert context.data_source == "HISTORICAL"
    assert "HISTORICAL" in context.reason
    assert context.execution_impact == "NONE"


def test_previous_session_context_prefers_online_over_historical_same_day(tmp_path):
    rows = _rows(tmp_path, "HISTORICAL") + _rows(tmp_path, "ONLINE")
    context = PreviousSessionContextService(_Database(rows)).latest_before("NSE_INDEX|Nifty 50", "2026-08-12")
    assert context.data_source == "ONLINE"
    assert context.snapshot_count == 2


def test_previous_session_context_rejects_replay_and_synthetic_sources(tmp_path):
    rows = _rows(tmp_path, "REPLAY") + _rows(tmp_path, "SYNTHETIC")
    context = PreviousSessionContextService(_Database(rows)).latest_before("NSE_INDEX|Nifty 50", "2026-08-12")
    assert context.status == "WAITING"
    assert context.data_source == "NONE"
    assert context.execution_impact == "NONE"


def test_previous_session_context_waits_without_prior_snapshots():
    context = PreviousSessionContextService(_Database([])).latest_before("NSE_INDEX|Nifty 50", "2026-08-12")
    assert context.status == "WAITING"
    assert context.execution_impact == "NONE"


def test_previous_session_context_ui_is_advisory_and_navigable():
    root = Path(__file__).resolve().parents[1]
    page = (root / "ui" / "pages" / "previous_session_context.py").read_text(encoding="utf-8")
    workspace = (root / "ui" / "workspace.py").read_text(encoding="utf-8")
    assert "Previous Session Context" in workspace
    assert "Data Source" in page
    assert "validated historical snapshots" in page
    assert "Carry-Forward Bias" in page
    assert "Closing PCR" in page
    assert "Closing Max Pain" in page
    assert "Dominant Strike" in page
    assert "Opening Narrative" in page
    assert "execution impact remains NONE" in page
