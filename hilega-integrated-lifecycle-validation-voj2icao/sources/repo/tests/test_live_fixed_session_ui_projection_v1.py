import json
from datetime import date, datetime

from market_lab.domain import Contract, IST, Quote, Snapshot
from market_lab.live_fixed_session_ui_projection_v1 import (
    attach_fixed_session_trends,
    load_fixed_anchor_index,
    project_fixed_session_ui,
)


def snapshot(at_hour=11, at_minute=55, bump=0):
    contracts=[];quotes=[]
    for strike in range(23150,23700,50):
        for side in ("CE","PE"):
            key=f"K-{strike}-{side}"
            contracts.append(Contract(key=key,strike=float(strike),side=side))
            baseline=strike*(2 if side=="CE" else 3)
            quotes.append(Quote(key=key,oi=baseline+bump,prev_oi=1))
    t=datetime(2026,9,21,at_hour,at_minute,10,tzinfo=IST)
    return Snapshot(provider="upstox",underlying="NSE_INDEX|Nifty 50",
        expiry=date(2026,9,22),started_at=t,received_at=t,spot=23420.8,
        spot_feed_at=t,catalog=contracts,quotes=quotes,raw={})


def anchor(provenance="ANCHOR_RECOVERED_UPSTOX_INTRADAY_1M"):
    legs=[]
    for strike in range(23150,23700,50):
        for side in ("CE","PE"):
            legs.append({"strike":float(strike),"side":side,
                "instrument_key":f"K-{strike}-{side}",
                "open_interest":strike*(2 if side=="CE" else 3)})
    ce=sum(x["open_interest"] for x in legs if x["side"]=="CE")
    pe=sum(x["open_interest"] for x in legs if x["side"]=="PE")
    return {"status":"AVAILABLE","provenance":provenance,
        "session_date":"2026-09-21","checkpoint_time":"2026-09-21T09:20:00+05:30",
        "source_candle_time":"2026-09-21T09:19:00+05:30" if "RECOVERED" in provenance else None,
        "source_semantics":"COMPLETED_1M_BOUNDARY" if "RECOVERED" in provenance else "FIRST_LIVE_SNAPSHOT_AT_OR_AFTER_CHECKPOINT_WITHIN_30S",
        "underlying":"NSE_INDEX|Nifty 50","expiry":"2026-09-22","atm":23400.0,
        "legs":legs,"ce_total":ce,"pe_total":pe,"fixed_pcr":pe/ce}


def missed_eval():
    return {"anchor_status":"missed","results":[{"mode":"fixed","atm":None,
        "strikes":[],"contract_keys":[],"expected":0,"received":0,
        "put_oi":0,"call_oi":0,"put_prev_oi":None,"call_prev_oi":None,
        "put_change_oi":None,"call_change_oi":None,"put_change_pct":None,
        "call_change_pct":None,"pcr":None,"issues":["anchor_missed"]}]}


def idx(a=None):
    a=a or anchor()
    return {("2026-09-21","NSE_INDEX|Nifty 50","2026-09-22"):a}


def test_anchor_index_latest_available_wins(tmp_path):
    p=tmp_path/"fixed-anchor.jsonl"
    a=anchor();older=dict(a,atm=23350.0)
    p.write_text(json.dumps(older)+"\n"+json.dumps(a)+"\n")
    got=load_fixed_anchor_index(p)[("2026-09-21","NSE_INDEX|Nifty 50","2026-09-22")]
    assert got["atm"]==23400.0


def test_recovered_projection_exact_11_strikes_22_contracts():
    ui=project_fixed_session_ui(snapshot(bump=10).model_dump(mode="json"),missed_eval(),anchor_index=idx())
    assert ui["status"]=="AVAILABLE"
    assert ui["provenance"]=="ANCHOR_RECOVERED_UPSTOX_INTRADAY_1M"
    assert ui["label"]=="RECOVERED ANCHOR"
    assert ui["atm"]==23400.0
    assert len(ui["rows"])==11
    assert ui["contract_count"]==22
    assert ui["ce_delta"]==110
    assert ui["pe_delta"]==110
    assert ui["display_result"]["received"]==22
    assert ui["display_result"]["expected"]==22


def test_live_anchor_projection_is_supported_and_labelled_live():
    a=anchor("ANCHOR_LIVE")
    ui=project_fixed_session_ui(snapshot(bump=5).model_dump(mode="json"),missed_eval(),anchor_index=idx(a))
    assert ui["status"]=="AVAILABLE"
    assert ui["provenance"]=="ANCHOR_LIVE"
    assert ui["label"]=="LIVE ANCHOR"
    assert ui["display_result"]["issues"]==[]


def test_projection_uses_anchor_not_provider_prev_oi():
    ui=project_fixed_session_ui(snapshot(bump=25).model_dump(mode="json"),missed_eval(),anchor_index=idx())
    assert ui["ce_delta"]==11*25
    assert ui["pe_delta"]==11*25
    assert all(r["call_change_oi"]==25 for r in ui["rows"])
    assert all(r["put_change_oi"]==25 for r in ui["rows"])


def test_missing_exact_current_contract_is_incomplete():
    payload=snapshot().model_dump(mode="json")
    payload["quotes"]=[q for q in payload["quotes"] if q["key"]!="K-23400-PE"]
    ui=project_fixed_session_ui(payload,missed_eval(),anchor_index=idx())
    assert ui["status"]=="INCOMPLETE"
    assert ui["current_pcr"] is None
    assert ui["display_result"]["pcr"] is None
    assert ui["missing_instrument_keys"]==["K-23400-PE"]


def test_projection_does_not_apply_before_anchor():
    s=snapshot(at_hour=9,at_minute=19)
    assert project_fixed_session_ui(s.model_dump(mode="json"),missed_eval(),anchor_index=idx()) is None


def test_fixed_session_trends_exact_horizons():
    history=[]
    for minute,bump in ((40,0),(45,10),(50,20),(55,30)):
        s=snapshot(at_hour=11,at_minute=minute,bump=bump)
        history.append({"id":minute,"fixed_session_ui":
            project_fixed_session_ui(s.model_dump(mode="json"),missed_eval(),anchor_index=idx())})
    attach_fixed_session_trends(history,tolerance_seconds=30,flat_threshold=0.000001)
    latest=history[-1]["fixed_session_trends"]
    assert latest["300"]["absolute_pcr_change"] is not None
    assert latest["900"]["absolute_pcr_change"] is not None
    assert latest["1800"]["classification"]=="UNAVAILABLE"
