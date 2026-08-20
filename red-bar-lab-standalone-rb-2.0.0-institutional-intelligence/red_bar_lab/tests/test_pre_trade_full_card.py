import json
import sqlite3
from types import SimpleNamespace

from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.ui.pre_trade_full_card import build_pre_trade_full_card


def _database(tmp_path):
    path = tmp_path / "pre_trade.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE candidate_lifecycle (
                id INTEGER PRIMARY KEY,
                trading_date TEXT,
                candidate_symbol TEXT,
                details TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO candidate_lifecycle VALUES (1,?,?,?,?)",
            (
                "2026-08-20",
                "NIFTY 24200 PE 25 AUG 26",
                json.dumps(
                    {
                        "pcr_oi": 1.18,
                        "delta": -0.46,
                        "current_price": 142.50,
                        "option_vwap": 139.80,
                    }
                ),
                "2026-08-20T09:32:20+05:30",
            ),
        )
        conn.commit()
    return SimpleNamespace(path=path)


def _diagnostics():
    return {
        "signal_id": "RBV2-CURRENT",
        "trading_date": "2026-08-20",
        "confirmation_timestamp": "2026-08-20T09:31:00+05:30",
        "pipeline_updated_at": "2026-08-20T09:32:16+05:30",
        "monitor_heartbeat": "2026-08-20T09:32:19+05:30",
        "monitor_state": "WAITING_FOR_V2_SIGNAL",
        "market_context_ready": True,
        "volume_structure_ready": True,
        "options_context_ready": True,
        "core_eligible": True,
        "hybrid_eligible": True,
        "committee_decision": "WAIT",
        "committee_reason": "FOREGROUND_COMMITTEE_APPROVED=0",
        "terminal_condition": "BEARISH_EMA10_LOST",
        "candidate_symbol": "NIFTY 24200 PE 25 AUG 26",
        "candidate_score": 100.0,
        "source_status": "CURRENT_DAY_RUNTIME",
    }


def test_pre_trade_card_shows_persisted_indicators_and_not_taken_reason(tmp_path):
    snapshot = RedBarV2UISnapshot(
        mode="PAPER",
        execution_scope="PAPER_TRADING_ONLY",
        reference_status="REFERENCE_READY",
        directional_state="ACTIVE_SIGNAL",
        direction="BEARISH",
        option_side="PE",
        index_rsi=38.4,
        futures_close=24192.0,
        futures_vwap=24210.0,
        last_evaluation_timestamp="2026-08-20T09:32:26+05:30",
    )

    card = build_pre_trade_full_card(_database(tmp_path), snapshot, _diagnostics())

    assert card["candidate"] == "NIFTY 24200 PE 25 AUG 26"
    assert card["trade_status"] == "NOT TAKEN"
    assert card["reason"] == "BEARISH_EMA10_LOST"
    assert card["pcr"] == 1.18
    assert card["delta"] == -0.46
    assert card["option_vwap_position"] == "ABOVE VWAP"
    assert round(card["option_vwap_gap_pct"], 2) == 1.93
    assert card["index_rsi"] == 38.4
    assert card["futures_vwap_position"] == "BELOW VWAP"
    assert card["gates"][-1]["Status"] == "FAIL"


def test_pre_trade_card_marks_approved_decision_as_taken(tmp_path):
    diagnostics = _diagnostics()
    diagnostics["committee_decision"] = "APPROVED"
    diagnostics["terminal_condition"] = None
    diagnostics["committee_reason"] = "COMMITTEE_APPROVED"
    snapshot = RedBarV2UISnapshot(
        reference_status="REFERENCE_READY",
        direction="BEARISH",
        option_side="PE",
    )

    card = build_pre_trade_full_card(_database(tmp_path), snapshot, diagnostics)

    assert card["trade_status"] == "TAKEN"
    assert card["reason"] == "COMMITTEE_APPROVED"
    assert card["gates"][-1]["Status"] == "PASS"


def test_pre_trade_card_does_not_invent_missing_candidate_metrics(tmp_path):
    diagnostics = _diagnostics()
    diagnostics["candidate_symbol"] = "NIFTY 24100 PE 25 AUG 26"
    snapshot = RedBarV2UISnapshot(reference_status="REFERENCE_READY")

    card = build_pre_trade_full_card(_database(tmp_path), snapshot, diagnostics)

    assert card["pcr"] is None
    assert card["delta"] is None
    assert card["option_vwap"] is None
    assert card["option_vwap_position"] == "UNAVAILABLE"
