from datetime import datetime, timedelta
import importlib.util
import sys
from pathlib import Path

P = Path(__file__).parents[1] / "scripts" / "analyze_control_failure_historical_v5.py"
spec = importlib.util.spec_from_file_location("v5", P)
v5 = importlib.util.module_from_spec(spec); sys.modules[spec.name] = v5; spec.loader.exec_module(v5)


def session_from_points(points):
    rows=[]; date="2026-09-18"; interval=50.0; atm=23400.0
    # points: time -> (spot, list of 5 per-strike imbalances)
    # synthesize prior/current OI cumulatively so requested rolling imbalances emerge.
    strikes=[atm+i*interval for i in range(-2,3)]
    ce={s:10_000_000.0 for s in strikes}; pe={s:10_000_000.0 for s in strikes}
    for time, spot, imbs in points:
        ts=datetime.fromisoformat(f"{date}T{time}:00+05:30")
        for s, imb in zip(strikes, imbs):
            # choose CE delta 0, PE delta = imbalance
            pe[s]+=imb
            rows.append({"timestamp":ts.isoformat(),"strike":s,"moving_atm":atm,"spot":spot,
                         "ce_open_interest":ce[s],"pe_open_interest":pe[s]})
    return {"session_date":date,"status":"AVAILABLE","strike_interval":interval,"rows":rows}


def test_decay_then_failure_detects_bullish_event():
    # 10:20 establishes prior velocity; 10:25 becomes more bearish; 10:30 decays; 10:35 price rises against bearish OI.
    pts=[
      ("10:15",100.0,[0,0,0,0,0]),
      ("10:20",95.0,[-100,-100,-100,-100,-100]),
      ("10:25",90.0,[-300,-300,-300,-300,-300]),
      ("10:30",85.0,[-50,-50,-50,-50,-50]),
      ("10:35",90.0,[-200,-200,-200,-200,-200]),
      ("10:40",100.0,[100,100,100,100,100]),
      ("10:45",110.0,[100,100,100,100,100]),
      ("10:50",115.0,[100,100,100,100,100]),
      ("10:55",120.0,[100,100,100,100,100]),
      ("11:00",125.0,[100,100,100,100,100]),
      ("11:05",130.0,[100,100,100,100,100]),
    ]
    candles=v5.build_candles(session_from_points(pts), wings=2)
    events=v5.detect_events(candles)
    bulls=[e for e in events if e.direction=="BULLISH"]
    assert bulls
    assert bulls[0].component_order == "DECAY_THEN_FAILURE"
    assert bulls[0].detected_checkpoint.endswith("10:35:00+05:30")
    assert bulls[0].move_5m == 10.0


def test_failure_then_decay_detects_bullish_event():
    pts=[
      ("13:00",100.0,[0,0,0,0,0]),
      ("13:05",95.0,[-100,-100,-100,-100,-100]),
      ("13:10",90.0,[-300,-300,-300,-300,-300]),
      ("13:15",100.0,[-500,-500,-500,-500,-500]),  # failure: price up, OI more bearish
      ("13:20",95.0,[-100,-100,-100,-100,-100]),  # decay after prior failure; current price does not fail bearish OI
      ("13:25",105.0,[100,100,100,100,100]),
      ("13:30",110.0,[100,100,100,100,100]),
      ("13:35",115.0,[100,100,100,100,100]),
      ("13:40",120.0,[100,100,100,100,100]),
      ("13:45",125.0,[100,100,100,100,100]),
      ("13:50",130.0,[100,100,100,100,100]),
    ]
    candles=v5.build_candles(session_from_points(pts), wings=2)
    events=v5.detect_events(candles)
    bulls=[e for e in events if e.direction=="BULLISH"]
    assert bulls
    assert bulls[0].component_order == "FAILURE_THEN_DECAY"
    assert bulls[0].detected_checkpoint.endswith("13:20:00+05:30")


def test_bearish_mirror_is_symmetric():
    pts=[
      ("11:00",100.0,[0,0,0,0,0]),
      ("11:05",105.0,[100,100,100,100,100]),
      ("11:10",110.0,[300,300,300,300,300]),
      ("11:15",115.0,[50,50,50,50,50]),   # bullish pressure decays
      ("11:20",110.0,[200,200,200,200,200]), # bullish OI but price down = failure
      ("11:25",100.0,[-100,-100,-100,-100,-100]),
      ("11:30",95.0,[-100,-100,-100,-100,-100]),
      ("11:35",90.0,[-100,-100,-100,-100,-100]),
      ("11:40",85.0,[-100,-100,-100,-100,-100]),
      ("11:45",80.0,[-100,-100,-100,-100,-100]),
      ("11:50",75.0,[-100,-100,-100,-100,-100]),
    ]
    candles=v5.build_candles(session_from_points(pts), wings=2)
    events=v5.detect_events(candles)
    bears=[e for e in events if e.direction=="BEARISH"]
    assert bears
    assert bears[0].component_order == "DECAY_THEN_FAILURE"
    assert bears[0].move_5m == 10.0
