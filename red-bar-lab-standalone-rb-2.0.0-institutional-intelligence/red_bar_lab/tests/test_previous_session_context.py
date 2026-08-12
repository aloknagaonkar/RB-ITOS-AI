from pathlib import Path
from types import SimpleNamespace
import json

import pandas as pd

from red_bar_lab.intelligence.previous_session_context import (
    PreviousSessionContextService,
    PreviousSessionHistoricalAdapter,
)


class _Database:
    def __init__(self, rows):
        self.rows = list(rows)

    def read_option_chain_history(self, instrument_key, from_date, to_date, limit=5000):
        return list(self.rows)

    def upsert_option_chain_history(self, row):
        self.rows = [item for item in self.rows if item.get("snapshot_key") != row.get("snapshot_key")]
        self.rows.append(dict(row))
        return len(self.rows)


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


def test_historical_artifact_adapter_persists_final_two_chain_snapshots(tmp_path):
    instrument = "NSE_INDEX|Nifty 50"
    day_root = tmp_path / "upstox" / "options" / "NSE_INDEX_Nifty_50" / "2026-08-11"
    candle_root = day_root / "candles"
    candle_root.mkdir(parents=True)
    contracts = [
        {"instrument_key": "CE1", "instrument_type": "CE", "strike_price": 24450, "trading_symbol": "NIFTY 24450 CE"},
        {"instrument_key": "PE1", "instrument_type": "PE", "strike_price": 24450, "trading_symbol": "NIFTY 24450 PE"},
    ]
    (day_root / "contracts.json").write_text(
        json.dumps({"expiry": "2026-08-18", "contracts": contracts}), encoding="utf-8"
    )
    times = ["2026-08-11T09:58:00Z", "2026-08-11T09:59:00Z", "2026-08-11T10:00:00Z"]
    pd.DataFrame({
        "timestamp": times, "close": [100, 102, 104], "volume": [1000, 1100, 1200], "oi": [5000, 5200, 5500]
    }).to_csv(candle_root / "CE1.csv", index=False)
    pd.DataFrame({
        "timestamp": times, "close": [95, 93, 91], "volume": [1200, 1250, 1300], "oi": [6000, 6100, 6200]
    }).to_csv(candle_root / "PE1.csv", index=False)

    database = _Database([])
    layout = SimpleNamespace(settings=SimpleNamespace(historical_root=tmp_path))
    readiness = PreviousSessionHistoricalAdapter(database, layout).ensure_previous_session(
        instrument, "2026-08-12"
    )

    assert readiness.status == "ADAPTED"
    assert readiness.previous_artifact_date == "2026-08-11"
    assert readiness.artifact_contracts == 2
    assert readiness.adapted_snapshots == 2
    assert len(database.rows) == 2
    assert all(row["collector_mode"] == "HISTORICAL" for row in database.rows)
    assert all(Path(row["chain_artifact_path"]).exists() for row in database.rows)

    context = PreviousSessionContextService(database).latest_before(instrument, "2026-08-12")
    assert context.status == "READY"
    assert context.data_source == "HISTORICAL"
    assert context.previous_trading_date == "2026-08-11"


def test_historical_artifact_adapter_reports_backfill_required_without_artifacts(tmp_path):
    database = _Database([])
    layout = SimpleNamespace(settings=SimpleNamespace(historical_root=tmp_path))
    readiness = PreviousSessionHistoricalAdapter(database, layout).ensure_previous_session(
        "NSE_INDEX|Nifty 50", "2026-08-12"
    )
    assert readiness.status == "BACKFILL_REQUIRED"
    assert readiness.adapted_snapshots == 0


def test_previous_session_context_waits_without_prior_snapshots():
    context = PreviousSessionContextService(_Database([])).latest_before("NSE_INDEX|Nifty 50", "2026-08-12")
    assert context.status == "WAITING"
    assert context.execution_impact == "NONE"


def test_previous_session_context_ui_is_advisory_and_navigable():
    root = Path(__file__).resolve().parents[1]
    page = (root / "ui" / "pages" / "previous_session_context.py").read_text(encoding="utf-8")
    workspace = (root / "ui" / "workspace.py").read_text(encoding="utf-8")
    assert "Previous Session Context" in workspace
    assert "Previous Session Data Readiness" in page
    assert "Adapted Snapshots" in page
    assert "Data Source" in page
    assert "validated historical snapshots" in page
    assert "Carry-Forward Bias" in page
    assert "Closing PCR" in page
    assert "Closing Max Pain" in page
    assert "Dominant Strike" in page
    assert "Opening Narrative" in page
    assert "execution impact remains NONE" in page
