from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from red_bar_lab.strategy.models import Direction, SignalAttempt, SignalState
from red_bar_lab.strategy.trade_engine import evaluate_active_signals, evaluate_break_even_1r, evaluate_eod_hold, evaluate_fixed_target, evaluate_risk_reward, evaluate_trailing_stop
from red_bar_lab.strategy.trade_models import ExitModel, ExitReason

IST=ZoneInfo("Asia/Kolkata")

def frame(rows):
    return pd.DataFrame([{"timestamp":pd.Timestamp(ts,tz=IST),"open":o,"high":h,"low":l,"close":c,"volume":0} for ts,o,h,l,c in rows])

def bullish_attempt():
    return SignalAttempt(state=SignalState.ACTIVE,direction=Direction.BULLISH,level_type="NEXT_RED_CANDLE",level_value=100,
        cross_timestamp=datetime(2026,8,5,9,20,tzinfo=IST),confirmation_timestamp=datetime(2026,8,5,9,26,tzinfo=IST),
        underlying_entry=103,cross_open=99,cross_high=102,cross_low=98,cross_close=101,
        confirmation_open=101,confirmation_high=104,confirmation_low=101,confirmation_close=103,confirmation_delay_minutes=2)

def test_fixed_target_tracks_post_target_continuation():
    data=frame([
        ("2026-08-05 09:27",103,110,102,108),
        ("2026-08-05 09:28",108,124,107,122),
        ("2026-08-05 09:29",122,150,120,145),
        ("2026-08-05 15:29",145,146,140,142),
    ])
    r=evaluate_fixed_target(data,bullish_attempt(),instrument_key="NIFTY",trading_date="2026-08-05",target_points=20)
    assert r.exit_reason is ExitReason.TARGET
    assert r.points==20 and r.session_mfe_points==47 and r.move_after_target_points==27
    assert r.session_extreme_price==150 and r.risk_points==5 and r.r_multiple==4

def test_risk_reward_2r():
    data=frame([("2026-08-05 09:27",103,114,102,112)])
    r=evaluate_risk_reward(data,bullish_attempt(),instrument_key="NIFTY",trading_date="2026-08-05",r_multiple=2)
    assert r.exit_model is ExitModel.RISK_REWARD
    assert r.target_points==10 and r.target_price==113 and r.exit_reason is ExitReason.TARGET

def test_trailing_stop():
    data=frame([
        ("2026-08-05 09:27",103,110,102,109),
        ("2026-08-05 09:28",109,125,116,124),
        ("2026-08-05 09:29",124,127,115,116),
    ])
    r=evaluate_trailing_stop(data,bullish_attempt(),instrument_key="NIFTY",trading_date="2026-08-05",trail_points=10)
    assert r.exit_reason is ExitReason.TRAILING_STOP and r.exit_price==117 and r.points==14

def test_break_even_after_one_r():
    data=frame([
        ("2026-08-05 09:27",103,109,102,108),
        ("2026-08-05 09:28",108,109,102,103),
    ])
    r=evaluate_break_even_1r(data,bullish_attempt(),instrument_key="NIFTY",trading_date="2026-08-05")
    assert r.exit_reason is ExitReason.BREAK_EVEN and r.exit_price==103 and r.points==0

def test_eod_hold():
    data=frame([
        ("2026-08-05 09:27",103,120,100,118),
        ("2026-08-05 15:29",118,130,110,125),
    ])
    r=evaluate_eod_hold(data,bullish_attempt(),instrument_key="NIFTY",trading_date="2026-08-05")
    assert r.exit_model is ExitModel.EOD_HOLD and r.points==22 and r.session_mfe_points==27

def test_all_exit_models_created():
    data=frame([
        ("2026-08-05 09:27",103,160,102,150),
        ("2026-08-05 15:29",150,165,140,155),
    ])
    results=evaluate_active_signals(data,[bullish_attempt()],instrument_key="NIFTY",trading_date="2026-08-05")
    assert len(results)==11
    assert len({r.trade_id for r in results})==11
    models={r.exit_model for r in results}
    assert {ExitModel.FIXED_TARGET,ExitModel.RISK_REWARD,ExitModel.TRAILING_STOP,ExitModel.BREAK_EVEN_1R,ExitModel.EOD_HOLD}.issubset(models)
