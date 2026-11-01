import json
from pathlib import Path

from market_lab.hilega_upstox_sandbox_dashboard_v1 import build_dashboard


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def append(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_dashboard_joins_entry_exit_and_calculates_estimated_pnl(tmp_path, monkeypatch):
    day = "2026-10-06"
    control = tmp_path / "control.json"
    dispatch = tmp_path / "dispatch.jsonl"
    journal = tmp_path / "events.jsonl"
    env = tmp_path / ".env"
    pid = tmp_path / "worker.pid"
    write_json(control, {"armed": True, "kill_switch": False, "session_date": day,
                         "max_orders": 4, "strategy_id": "HILEGA_DIRECTIONAL_SHADOW_V1"})
    env.write_text(f"HILEGA_UPSTOX_SANDBOX_JOURNAL={journal}\n")
    common = {"session_date": day, "trade_id": "trade-1", "direction": "BULLISH",
              "option_type": "CE", "instrument_key": "NSE_FO|1", "quantity": 65,
              "status": "ACCEPTED", "terminal": True, "strategy_id": "HILEGA_DIRECTIONAL_SHADOW_V1"}
    append(dispatch, {**common, "event_id": "entry-1", "event_type": "ENTRY",
                      "timestamp": f"{day}T10:00:00+05:30", "broker_order_id": "buy-1"})
    append(dispatch, {**common, "event_id": "exit-1", "event_type": "EXIT",
                      "timestamp": f"{day}T10:30:00+05:30", "broker_order_id": "sell-1"})
    append(journal, {"event_id": "entry-1", "terminal": True, "observed_option_price": 100})
    append(journal, {"event_id": "exit-1", "terminal": True, "observed_option_price": 110})
    monkeypatch.setenv("LIVE_SHADOW_STRATEGY", "HILEGA_DIRECTIONAL_SHADOW_V1")

    result = build_dashboard(control, dispatch, env, pid)
    assert result["active_trade"] is None
    assert result["pnl"]["closed_estimated_rupees"] == 650
    assert result["pnl"]["wins"] == 1
    assert result["completed_trades"][0]["entry_time"].endswith("+05:30")
    assert result["safety"]["live_execution_enabled"] is False


def test_dashboard_exposes_strategy_mismatch(tmp_path, monkeypatch):
    control = tmp_path / "control.json"
    write_json(control, {"armed": True, "session_date": "2026-10-06",
                         "strategy_id": "OLD_STRATEGY", "max_orders": 4})
    monkeypatch.setenv("LIVE_SHADOW_STRATEGY", "NEW_STRATEGY")
    result = build_dashboard(control, tmp_path / "missing.jsonl", tmp_path / ".env", tmp_path / "pid")
    assert result["strategy"]["strategy_match"] is False
    assert result["strategy"]["active_strategy_id"] == "NEW_STRATEGY"
