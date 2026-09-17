from __future__ import annotations

import argparse, csv, json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL = "OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1"
IST = "+05:30"


def rows_from_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in ("rows", "data", "items", "candles"):
            if isinstance(payload.get(k), list):
                return [x for x in payload[k] if isinstance(x, dict)]
    raise ValueError("No row list found in JSON payload")


def f(row: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def s(row: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = row.get(k)
        if v is not None:
            return str(v)
    return None


def dt(v: str) -> datetime:
    return datetime.fromisoformat(v)


def round_atm(spot: float, step: float) -> float:
    return round(spot / step) * step


def unique_glob(pattern: str) -> Path | None:
    m = sorted(Path(".").glob(pattern))
    return m[0] if len(m) == 1 else None


def auto_positioning(date: str) -> Path | None:
    return unique_glob(f"data/historical-positioning-cache-*/*NSE_INDEX_Nifty_50__{date}__*__w5.json")


def auto_option(date: str) -> Path | None:
    return unique_glob(f"data/historical-option-ohlc-cache-*/*NSE_INDEX_Nifty_50__{date}__*__w5.json")


def auto_futures() -> Path | None:
    p = Path("data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv")
    return p if p.exists() else None


def load_positioning(path: Path, date: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in rows_from_json(payload):
        ts = s(r, "timestamp", "ts", "time")
        strike = f(r, "strike", "strike_price")
        spot = f(r, "spot", "underlying_price", "underlying_spot", "index_price")
        ce = f(r, "ce_open_interest", "ce_oi")
        pe = f(r, "pe_open_interest", "pe_oi")
        if ts and ts.startswith(date) and strike is not None and ce is not None and pe is not None:
            out.append({"timestamp": ts, "strike": strike, "spot": spot, "ce_oi": ce, "pe_oi": pe})
    if not out:
        raise ValueError(f"No usable positioning rows in {path}")
    return out


def load_option_fallback(path: Path | None, date: str) -> dict[tuple[str, float, str], float]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for r in rows_from_json(payload):
        ts = s(r, "timestamp", "ts", "time")
        strike = f(r, "strike", "strike_price")
        side = (s(r, "side", "option_type", "type") or "").upper()
        oi = f(r, "open_interest", "oi")
        if ts and ts.startswith(date) and strike is not None and side in {"CE", "PE"} and oi is not None:
            out[(ts, strike, side)] = oi
    return out


def sum_side(ts: str, strikes: list[float], side: str, exact, fallback):
    field = "ce_oi" if side == "CE" else "pe_oi"
    total, missing, fb_used = 0.0, [], []
    for strike in strikes:
        r = exact.get((ts, float(strike)))
        if r is not None and r.get(field) is not None:
            total += float(r[field]); continue
        fb = fallback.get((ts, float(strike), side))
        if fb is not None:
            total += float(fb); fb_used.append(strike); continue
        missing.append(strike)
    return (None if missing else total), missing, fb_used


@dataclass(frozen=True)
class LabelRange:
    start: str
    end: str
    label: str
    def contains(self, hhmm: str) -> bool:
        return self.start <= hhmm <= self.end


def parse_label(raw: str) -> LabelRange:
    left, label = raw.rsplit(":", 1)
    start, end = left.split("-", 1)
    return LabelRange(start, end, label.upper())


def classify_futures_oi(price_change: float | None, oi_change: float | None):
    if price_change is None or oi_change is None:
        return "UNAVAILABLE", "NEUTRAL"
    if price_change == 0 or oi_change == 0:
        return "UNCLASSIFIED", "NEUTRAL"
    if price_change > 0 and oi_change > 0: return "LONG_BUILDUP", "BULLISH"
    if price_change < 0 and oi_change > 0: return "SHORT_BUILDUP", "BEARISH"
    if price_change > 0 and oi_change < 0: return "SHORT_COVERING", "BULLISH"
    return "LONG_UNWINDING", "BEARISH"


def load_futures(path: Path, date: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        raw = list(csv.DictReader(fh))
    out = []
    for r in raw:
        ts = s(r, "timestamp", "ts", "time", "datetime")
        if not ts or not ts.startswith(date): continue
        vals = [f(r, k) for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in vals): continue
        out.append({"timestamp": ts, "open": vals[0], "high": vals[1], "low": vals[2], "close": vals[3], "volume": vals[4], "oi": f(r, "open_interest", "oi", "openInterest")})
    out.sort(key=lambda x: x["timestamp"])
    if not out: raise ValueError(f"No futures rows for {date} in {path}")
    return out


def aggregate_completed_5m(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by = {dt(r["timestamp"]): r for r in rows}
    times = sorted(by)
    start = times[0].replace(hour=9, minute=15, second=0, microsecond=0)
    last = times[-1]
    out = {}; cpv = 0.0; cvol = 0.0
    while start <= last:
        block = [by.get(start + timedelta(minutes=i)) for i in range(5)]
        if all(x is not None for x in block):
            o = float(block[0]["open"]); h = max(float(x["high"]) for x in block); l = min(float(x["low"]) for x in block); c = float(block[-1]["close"])
            vol = sum(float(x["volume"]) for x in block)
            oi_vals = [x["oi"] for x in block if x.get("oi") is not None]
            oi = float(oi_vals[-1]) if oi_vals else None
            cpv += ((h + l + c) / 3.0) * vol; cvol += vol
            available = (start + timedelta(minutes=5)).isoformat()
            out[available] = {"bar_start": start.isoformat(), "close": c, "oi": oi, "vwap": cpv / cvol if cvol else None}
        start += timedelta(minutes=5)
    return out


def checkpoints(date: str):
    t = datetime.fromisoformat(f"{date}T09:20:00{IST}"); end = datetime.fromisoformat(f"{date}T15:25:00{IST}")
    while t <= end:
        yield t.isoformat(); t += timedelta(minutes=5)


def sign(v):
    return "NA" if v is None else "POS" if v > 0 else "NEG" if v < 0 else "ZERO"



def load_strategy_events(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def walk(x):
        if isinstance(x, dict):
            if x.get("timestamp") and x.get("event_type"):
                out[str(x["timestamp"])].append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(payload)
    return out


def summarize_strategy_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    types = [str(e.get("event_type")) for e in events]
    directions = [str(e.get("direction")) for e in events if e.get("direction")]
    p1 = next((e for e in events if e.get("event_type") == "P1_DETECTED"), None)
    p2c = next((e for e in events if e.get("event_type") == "P2_CONFIRMED_RUNTIME"), None)
    p2f = next((e for e in events if e.get("event_type") == "P2_FAILED"), None)
    vwfail = next((e for e in events if e.get("event_type") == "VWAP_NOT_ALIGNED"), None)
    wait = next((e for e in events if e.get("event_type") == "WAIT_P2"), None)
    return {
        "strategy_events": ",".join(types),
        "strategy_directions": ",".join(directions),
        "strategy_p1": p1.get("direction") if p1 else None,
        "strategy_wait_p2": wait.get("direction") if wait else None,
        "strategy_p2_confirmed": p2c.get("direction") if p2c else None,
        "strategy_p2_failed": p2f.get("direction") if p2f else None,
        "strategy_vwap_rejected": vwfail.get("direction") if vwfail else None,
    }


def interpretation_text(row: dict[str, Any]) -> str:
    parts = []
    oi = row.get("futures_oi_status")
    if oi and oi != "UNAVAILABLE":
        parts.append(f"FUTURES_OI={oi}")
    imb = row.get("imbalance_5m")
    if imb is not None:
        parts.append("OPTION_OI=BULLISH" if imb > 0 else "OPTION_OI=BEARISH" if imb < 0 else "OPTION_OI=FLAT")
    pcr = row.get("pcr_change_5m")
    if pcr is not None:
        parts.append("PCR=RISING" if pcr > 0 else "PCR=FALLING" if pcr < 0 else "PCR=FLAT")
    parts.append(f"VWAP={row.get('vwap_side')}")
    parts.append(f"CONSENSUS={row.get('consensus_hint')}")
    return " | ".join(parts)


def build_audit(date: str, positioning_file: Path, futures_csv: Path, option_ohlc_file: Path | None = None, strike_step: float = 50.0, wings: int = 5, labels: list[LabelRange] | None = None, strategy_events_json: Path | None = None):
    labels = labels or []
    pos = load_positioning(positioning_file, date)
    by_ts = defaultdict(list); exact = {}
    for r in pos:
        by_ts[r["timestamp"]].append(r); exact[(r["timestamp"], float(r["strike"]))] = r
    fallback = load_option_fallback(option_ohlc_file, date)
    fut = aggregate_completed_5m(load_futures(futures_csv, date))
    strategy_map = load_strategy_events(strategy_events_json)
    cps = list(checkpoints(date))

    base_rows = by_ts.get(cps[0], [])
    spots = [x["spot"] for x in base_rows if x["spot"] is not None]
    if not spots: raise ValueError("09:20 spot unavailable")
    morning_atm = round_atm(float(spots[0]), strike_step)
    fixed_strikes = [morning_atm + i*strike_step for i in range(-wings, wings+1)]
    base_ce, miss_ce, _ = sum_side(cps[0], fixed_strikes, "CE", exact, fallback)
    base_pe, miss_pe, _ = sum_side(cps[0], fixed_strikes, "PE", exact, fallback)
    if base_ce is None or base_pe is None:
        raise ValueError(f"09:20 fixed baseline incomplete CE={miss_ce} PE={miss_pe}")

    rows=[]; prev_fc=None; prev_foi=None; bull_streak=0; bear_streak=0
    for ts in cps:
        rs = by_ts.get(ts, []); spots = [x["spot"] for x in rs if x["spot"] is not None]
        if not spots:
            rows.append({"timestamp": ts, "status": "MISSING_POSITIONING_CHECKPOINT"}); continue
        spot=float(spots[0]); atm=round_atm(spot, strike_step)
        moving=[atm+i*strike_step for i in range(-wings,wings+1)]
        ce, ce_miss, ce_fb = sum_side(ts,moving,"CE",exact,fallback); pe, pe_miss, pe_fb=sum_side(ts,moving,"PE",exact,fallback)
        prev_same = {}
        for minutes in (5, 10, 15):
            pts = (dt(ts)-timedelta(minutes=minutes)).isoformat()
            pce,_,_=sum_side(pts,moving,"CE",exact,fallback)
            ppe,_,_=sum_side(pts,moving,"PE",exact,fallback)
            prev_same[minutes] = (pce, ppe)

        pce5,ppe5 = prev_same[5]
        ce_d=(ce-pce5) if ce is not None and pce5 is not None else None
        pe_d=(pe-ppe5) if pe is not None and ppe5 is not None else None
        imb=(pe_d-ce_d) if ce_d is not None and pe_d is not None else None

        def horizon_delta(minutes):
            pce,ppe = prev_same[minutes]
            ced = (ce-pce) if ce is not None and pce is not None else None
            ped = (pe-ppe) if pe is not None and ppe is not None else None
            im = (ped-ced) if ced is not None and ped is not None else None
            return ced,ped,im

        ce_d10,pe_d10,imb10 = horizon_delta(10)
        ce_d15,pe_d15,imb15 = horizon_delta(15)

        pcr=(pe/ce) if ce not in (None,0) and pe is not None else None

        def previous_same_pcr(minutes):
            pce,ppe = prev_same[minutes]
            return (ppe/pce) if pce not in (None,0) and ppe is not None else None

        pcr_prev5 = previous_same_pcr(5)
        pcr_prev10 = previous_same_pcr(10)
        pcr_prev15 = previous_same_pcr(15)
        pcr_d=(pcr-pcr_prev5) if pcr is not None and pcr_prev5 is not None else None
        pcr_d10=(pcr-pcr_prev10) if pcr is not None and pcr_prev10 is not None else None
        pcr_d15=(pcr-pcr_prev15) if pcr is not None and pcr_prev15 is not None else None
        fce,fce_miss,fce_fb=sum_side(ts,fixed_strikes,"CE",exact,fallback); fpe,fpe_miss,fpe_fb=sum_side(ts,fixed_strikes,"PE",exact,fallback)
        ce_s=(fce-base_ce) if fce is not None else None; pe_s=(fpe-base_pe) if fpe is not None else None; sess=(pe_s-ce_s) if ce_s is not None and pe_s is not None else None

        fr=fut.get(ts); fc=fr["close"] if fr else None; foi=fr["oi"] if fr else None
        pc=(fc-prev_fc) if fc is not None and prev_fc is not None else None
        prev10=fut.get((dt(ts)-timedelta(minutes=10)).isoformat())
        prev15=fut.get((dt(ts)-timedelta(minutes=15)).isoformat())
        pc10=(fc-prev10["close"]) if fc is not None and prev10 and prev10.get("close") is not None else None
        pc15=(fc-prev15["close"]) if fc is not None and prev15 and prev15.get("close") is not None else None
        oc=(foi-prev_foi) if foi is not None and prev_foi is not None else None
        oi_status, oi_dir=classify_futures_oi(pc,oc)
        if oi_dir=="BULLISH": bull_streak+=1; bear_streak=0
        elif oi_dir=="BEARISH": bear_streak+=1; bull_streak=0
        else: bull_streak=0; bear_streak=0
        vw=fr["vwap"] if fr else None; vd=(fc-vw) if fc is not None and vw is not None else None
        vs="ABOVE" if vd is not None and vd>0 else "BELOW" if vd is not None and vd<0 else "AT" if vd==0 else "UNAVAILABLE"
        bv = int(imb is not None and imb>0)+int(pcr_d is not None and pcr_d>0)+int(oi_dir=="BULLISH")+int(vs=="ABOVE")
        sv = int(imb is not None and imb<0)+int(pcr_d is not None and pcr_d<0)+int(oi_dir=="BEARISH")+int(vs=="BELOW")
        hint="BULLISH" if bv>=3 and bv>sv else "BEARISH" if sv>=3 and sv>bv else "MIXED"
        hhmm=ts[11:16]; label=next((x.label for x in labels if x.contains(hhmm)),None)
        rows.append({
            "timestamp":ts,"status":"PASS","spot":spot,"moving_atm":atm,"moving_strikes":",".join(str(int(x)) for x in moving),
            "ce_oi":ce,"pe_oi":pe,"ce_delta_5m":ce_d,"pe_delta_5m":pe_d,"imbalance_5m":imb,"imbalance_sign":sign(imb),
            "ce_delta_10m":ce_d10,"pe_delta_10m":pe_d10,"imbalance_10m":imb10,
            "ce_delta_15m":ce_d15,"pe_delta_15m":pe_d15,"imbalance_15m":imb15,
            "pcr_current":pcr,"pcr_previous_same_strikes_5m":pcr_prev5,"pcr_change_5m":pcr_d,"pcr_change_sign":sign(pcr_d),
            "pcr_change_10m":pcr_d10,"pcr_change_15m":pcr_d15,
            "morning_fixed_atm":morning_atm,"fixed_strikes":",".join(str(int(x)) for x in fixed_strikes),"fixed_ce_oi":fce,"fixed_pe_oi":fpe,
            "ce_session_delta":ce_s,"pe_session_delta":pe_s,"session_imbalance":sess,
            "futures_bar_start":fr["bar_start"] if fr else None,"futures_close":fc,"futures_price_change_5m":pc,"futures_price_change_10m":pc10,"futures_price_change_15m":pc15,"futures_oi":foi,"futures_oi_change_5m":oc,
            "futures_oi_status":oi_status,"futures_oi_direction":oi_dir,"bullish_oi_status_streak":bull_streak,"bearish_oi_status_streak":bear_streak,
            "vwap":vw,"vwap_distance":vd,"vwap_side":vs,"bullish_evidence_votes":bv,"bearish_evidence_votes":sv,"consensus_hint":hint,
            "evaluation_label":label,"fallback_used":bool(ce_fb or pe_fb or fce_fb or fpe_fb),
            "moving_missing_ce":",".join(map(str,ce_miss)),"moving_missing_pe":",".join(map(str,pe_miss)),"fixed_missing_ce":",".join(map(str,fce_miss)),"fixed_missing_pe":",".join(map(str,fpe_miss)),
            **summarize_strategy_events(strategy_map.get(ts, [])),
        })
        rows[-1]["interpretation"] = interpretation_text(rows[-1])
        if fc is not None: prev_fc=fc
        if foi is not None: prev_foi=foi
    return {"status":"PASS","model":MODEL,"session_date":date,"research_wings":wings,"research_strike_count":2*wings+1,"positioning_file":str(positioning_file),"option_ohlc_file":str(option_ohlc_file) if option_ohlc_file else None,"futures_csv":str(futures_csv),"strategy_events_json":str(strategy_events_json) if strategy_events_json else None,"morning_fixed_atm":morning_atm,"fixed_strikes":fixed_strikes,"rows":rows}


def write_csv(path: Path, rows: list[dict[str,Any]]):
    path.parent.mkdir(parents=True,exist_ok=True); fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fields.append(k)
    with path.open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--session-date",required=True); ap.add_argument("--positioning-file",type=Path); ap.add_argument("--option-ohlc-file",type=Path); ap.add_argument("--futures-csv",type=Path)
    ap.add_argument("--strike-step",type=float,default=50.0); ap.add_argument("--moving-wings",type=int,default=5); ap.add_argument("--label",action="append",default=[]); ap.add_argument("--strategy-events-json",type=Path)
    ap.add_argument("--csv",type=Path); ap.add_argument("--json-output",type=Path)
    a=ap.parse_args(); pos=a.positioning_file or auto_positioning(a.session_date); opt=a.option_ohlc_file or auto_option(a.session_date); fut=a.futures_csv or auto_futures()
    if pos is None: raise SystemExit("Could not uniquely resolve positioning file; pass --positioning-file")
    if fut is None: raise SystemExit("Could not resolve futures CSV; pass --futures-csv")
    report=build_audit(a.session_date,pos,fut,opt,a.strike_step,a.moving_wings,[parse_label(x) for x in a.label],a.strategy_events_json)
    if a.csv: write_csv(a.csv,report["rows"])
    if a.json_output:
        a.json_output.parent.mkdir(parents=True,exist_ok=True); a.json_output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__": main()
