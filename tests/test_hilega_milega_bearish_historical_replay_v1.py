from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import HistoricalCandle
from market_lab.hilega_milega_bearish_historical_replay_v1 import (
    _decision_rows,
    _pair_trades,
    replay_bearish_sessions,
)
from market_lab.hilega_milega_bearish_strategy_v1 import HilegaMilegaBearishEngineV1
from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar, IndicatorSnapshot

IST=ZoneInfo("Asia/Kolkata")
UTC=ZoneInfo("UTC")


def bar(hhmm:str, close:float=100.0)->FiveMinuteBar:
    h,m=map(int,hhmm.split(":"))
    return FiveMinuteBar(datetime(2026,9,17,h,m,tzinfo=IST),close,close+1,close-1,close,100)


def ind(rsi:float,ema:float,wma:float)->IndicatorSnapshot:
    return IndicatorSnapshot(rsi,ema,wma)


def test_pair_bearish_trade_uses_down_move_as_positive():
    e=HilegaMilegaBearishEngineV1()
    events=[]
    events += e.process_enriched_bar_for_test(bar("10:00"),ind(52,50,55))
    events += e.process_enriched_bar_for_test(bar("10:05",100),ind(45,48,51))
    events += e.process_enriched_bar_for_test(bar("10:10",92),ind(46,47,50))
    events += e.process_enriched_bar_for_test(bar("10:15",95),ind(51,49,50))
    trades=_pair_trades(events,date(2026,9,17))
    assert len(trades)==1
    assert trades[0].points==5.0
    assert trades[0].outcome=="POSITIVE"


def test_decision_rows_explain_bearish_arm_wait():
    cp="2026-09-17T10:05:00+05:30"
    rows=[
      {"checkpoint":cp,"stage":"STRATEGY_DECISION","status":"EVALUATED","payload":{
        "state_before":"BEARISH_PATH1_IDLE","bar_close":100,
        "rsi9":53,"ema3_rsi":54.5,"wma21_rsi":50,
        "previous_rsi9":55,"previous_ema3_rsi":54,"previous_wma21_rsi":50,
        "rsi_cross_ema_down":True,"rsi_cross_wma_up":False,
        "rsi_lt_50":False,"rsi_lt_wma":False,"ema_lt_wma":False,
        "rsi_falling":True,"ema_falling":False,"full_alignment":False}},
      {"checkpoint":cp,"stage":"STRATEGY_TRANSITION","status":"BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN","payload":{}},
      {"checkpoint":cp,"stage":"STRATEGY_DECISION_RESULT","status":"COMPLETE","payload":{
        "state_after":"BEARISH_PATH1_ARMED","route_a_eligible":True,"route_a_pass":False,
        "route_a_fail_reasons":["RSI_NOT_BELOW_50","RSI_NOT_BELOW_WMA21"],
        "route_b_eligible":True,"route_b_pass":False,
        "route_b_fail_reasons":["NEITHER_RSI_NOR_EMA_BELOW_WMA21","EMA_NOT_FALLING"]}}
    ]
    out=_decision_rows(rows,include_all=False)
    assert out[0]["final_decision"]=="ARMED_WAITING"
    assert "RSI_NOT_BELOW_50" in out[0]["reasons"]


class FallingGateway:
    def historical_candles(self,instrument_key:str,session_date:date):
        if session_date!=date(2026,9,17):
            return []
        start=datetime(2026,9,17,9,15,tzinfo=IST)
        rows=[]
        price=23100.0
        for i in range(375):
            ts=start+timedelta(minutes=i)
            # deterministic descending session with periodic small bounces
            price += -0.22 if i%11 else 0.35
            rows.append(HistoricalCandle(
                provider="upstox",instrument_key=instrument_key,session_date=session_date,
                timestamp=ts.astimezone(UTC),open=price+0.05,high=price+0.25,low=price-0.25,
                close=price,volume=100,open_interest=None))
        return rows


def test_bearish_replay_writes_audit_validation_and_summary(tmp_path):
    result=replay_bearish_sessions(
        gateway=FallingGateway(),
        dates=[date(2026,9,17)],
        warmup_calendar_days=0,
        cache_root=tmp_path/"cache",
        output_root=tmp_path/"out",
    )
    assert result["summary"]["sessions_passed"]==1
    assert result["observation_only"] is True
    assert result["execution_enabled"] is False
    assert result["rule_status"]=="CANDIDATE_MIRROR_UNDER_VALIDATION"
    d=tmp_path/"out"/"2026-09-17"
    for name in [
      "step-audit.jsonl",
      "bearish-trades.csv",
      "bearish-signal-decision-audit.csv",
      "bearish-signal-decision-audit.json",
      "bearish-candle-by-candle-audit.csv",
      "bearish-candle-by-candle-audit.json",
      "bearish-manual-validation.txt",
    ]:
        assert (d/name).exists(),name
    text=(d/"bearish-manual-validation.txt").read_text()
    assert "BEARISH MANUAL VALIDATION" in text
    summary=json.loads((tmp_path/"out"/"multi-session-bearish-summary.json").read_text())
    assert summary["manual_validation_required"] is True
