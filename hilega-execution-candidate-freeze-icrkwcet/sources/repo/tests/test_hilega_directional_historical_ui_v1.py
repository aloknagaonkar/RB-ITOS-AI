from pathlib import Path

from market_lab.hilega_directional_historical_ui_v1 import build_directional_historical_dashboard
import market_lab.hilega_directional_historical_ui_v1 as m


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_directional_historical_dashboard_combines_ce_and_pe(tmp_path, monkeypatch):
    day = "2026-09-17"
    droot = tmp_path / "directional"
    broot = tmp_path / "bullish"
    proot = tmp_path / "pe"

    _write(
        droot / day / "directional-trades.csv",
        "session_date,direction,entry_time,entry_event,entry_price,exit_time,exit_event,exit_price,points,outcome,holding_minutes\n"
        f"{day},BULLISH,09:25,ENTRY_BULL,100,10:20,EXIT_BULL,110,10,POSITIVE,55\n"
        f"{day},BEARISH,10:30,ENTRY_BEARISH_ROUTE_B_STRUCTURAL,110,11:30,STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21,100,10,POSITIVE,60\n",
    )
    _write(broot / day / "step-audit.jsonl", "{}\n")
    _write(
        broot / day / "ce-shadow-trades.csv",
        "session_date,trade_index,entry_time,exit_time,entry_event,exit_event,signal_spot,atm,expiry,status,complete_legs,issue\n"
        f"{day},11,09:25,10:20,ENTRY_BULL,EXIT_BULL,23250,23250,2026-09-22,CLOSED,5,\n",
    )
    _write(
        broot / day / "ce-shadow-legs.csv",
        "trade_index,relation_to_atm,strike,instrument_key,entry_timestamp,entry_open,exit_timestamp,exit_open,realized_points,realized_return_pct,mfe_points,mae_points\n"
        + "\n".join(
            f"11,{rel},{23250+rel*50},CE{rel},{day}T09:30:00+05:30,{100+rel},{day}T10:25:00+05:30,{110+rel},10,10,20,-2"
            for rel in (-2,-1,0,1,2)
        ) + "\n",
    )
    _write(
        proot / day / "pe-shadow-trades.csv",
        "session_date,trade_index,entry_time,exit_time,entry_event,exit_event,signal_spot,atm,expiry,status,complete_legs,issue\n"
        f"{day},12,10:30,11:30,ENTRY_BEARISH_ROUTE_B_STRUCTURAL,STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21,23273.6,23250,2026-09-22,CLOSED,5,\n",
    )
    _write(
        proot / day / "pe-shadow-legs.csv",
        "trade_index,relation_to_atm,strike,instrument_key,entry_timestamp,entry_open,exit_timestamp,exit_open,realized_points,realized_return_pct,mfe_points,mae_points\n"
        + "\n".join(
            f"12,{rel},{23250+rel*50},PE{rel},{day}T10:35:00+05:30,{100+rel},{day}T11:35:00+05:30,{110+rel},10,10,20,-2"
            for rel in (-2,-1,0,1,2)
        ) + "\n",
    )

    monkeypatch.setattr(m, "DIRECTIONAL_ROOT", droot)
    monkeypatch.setattr(m, "CE_ROOT", broot)
    monkeypatch.setattr(m, "PE_ROOT", proot)

    result = build_directional_historical_dashboard(day)
    assert result["accepted_bullish_trades"] == 1
    assert result["accepted_bearish_trades"] == 1
    assert result["trade_count"] == 2
    assert result["trades"][0]["direction"] == "BULLISH"
    assert result["trades"][0]["option_side"] == "CE"
    assert result["trades"][1]["direction"] == "BEARISH"
    assert result["trades"][1]["option_side"] == "PE"
    assert len(result["trades"][1]["legs"]) == 5
    assert result["trades"][1]["complete"] is True
