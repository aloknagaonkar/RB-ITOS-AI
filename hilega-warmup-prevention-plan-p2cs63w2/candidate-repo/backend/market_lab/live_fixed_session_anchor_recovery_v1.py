"""Strict late-start fixed-session OI anchor recovery for current-day NIFTY shadow use.

No nearest strike/timestamp, no interpolation, no synthetic OI, no partial basket.
Recovered 09:20 anchors use the completed 09:19 1-minute candle.
"""
from __future__ import annotations

import json, math, os
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from .domain import IST, PCRConfig, Snapshot

MODEL = "LIVE_FIXED_SESSION_ANCHOR_RECOVERY_V1"
PROV_LIVE = "ANCHOR_LIVE"
PROV_RECOVERED = "ANCHOR_RECOVERED_UPSTOX_INTRADAY_1M"
PROV_MISSING = "ANCHOR_MISSING"
PROV_NA = "NOT_APPLICABLE"

class AnchorRecoveryError(RuntimeError):
    pass

@dataclass(frozen=True)
class FixedAnchorLeg:
    strike: float
    side: Literal["CE", "PE"]
    instrument_key: str
    open_interest: int

@dataclass(frozen=True)
class FixedSessionAnchor:
    model: str
    status: str
    provenance: str
    session_date: str
    checkpoint_time: str
    source_candle_time: str | None
    source_semantics: str | None
    provider: str | None
    underlying: str
    expiry: str
    spot: float | None
    atm: float | None
    strike_interval: float
    wings: int
    strikes: tuple[float, ...]
    legs: tuple[FixedAnchorLeg, ...]
    ce_total: int | None
    pe_total: int | None
    fixed_pcr: float | None
    fallback_used: bool
    issue: str | None = None
    def payload(self):
        d = asdict(self); d["strikes"] = list(self.strikes); d["legs"] = [asdict(x) for x in self.legs]; return d

@dataclass(frozen=True)
class FixedSessionMetrics:
    status: str
    anchor_provenance: str
    checkpoint: str
    fixed_atm: float
    strikes: tuple[float, ...]
    baseline_ce_oi: int
    baseline_pe_oi: int
    current_ce_oi: int | None
    current_pe_oi: int | None
    ce_delta: int | None
    pe_delta: int | None
    imbalance: int | None
    baseline_pcr: float | None
    current_pcr: float | None
    pcr_change: float | None
    missing_instrument_keys: tuple[str, ...]
    def payload(self):
        d = asdict(self); d["strikes"] = list(self.strikes); d["missing_instrument_keys"] = list(self.missing_instrument_keys); return d

def _anchor_dt(session_date: date, value: str) -> datetime:
    try:
        h, m = map(int, value.split(":"))
        return datetime.combine(session_date, time(h, m), tzinfo=IST)
    except Exception as exc:
        raise AnchorRecoveryError("INVALID_ANCHOR_TIME") from exc

def _round_half_up(spot: float, interval: float) -> float:
    if not math.isfinite(spot) or spot <= 0 or interval <= 0:
        raise AnchorRecoveryError("INVALID_SPOT_OR_INTERVAL")
    q = (Decimal(str(spot)) / Decimal(str(interval))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(q * Decimal(str(interval)))

def _pcr(pe, ce):
    return None if ce in (None, 0) or pe is None else float(pe) / float(ce)

class UpstoxIntradayAnchorSourceV1:
    def __init__(self, token: str, client=None):
        if not token: raise AnchorRecoveryError("UPSTOX_ACCESS_TOKEN_MISSING")
        self.token = token
        self.client = client or httpx.Client(base_url="https://api.upstox.com", timeout=20)
        self.owns = client is None
    def close(self):
        if self.owns: self.client.close()
    def _get(self, path, params=None):
        try:
            r = self.client.get(path, params=params, headers={"Accept":"application/json","Authorization":f"Bearer {self.token}"})
        except httpx.RequestError as exc:
            raise AnchorRecoveryError("UPSTOX_NETWORK_ERROR") from exc
        if r.status_code in (401,403): raise AnchorRecoveryError("UPSTOX_AUTH_OR_ENTITLEMENT_REJECTED")
        if r.status_code == 429: raise AnchorRecoveryError("UPSTOX_RATE_LIMIT")
        if r.status_code != 200: raise AnchorRecoveryError(f"UPSTOX_HTTP_{r.status_code}")
        try: body = r.json()
        except Exception as exc: raise AnchorRecoveryError("UPSTOX_INVALID_JSON") from exc
        if not isinstance(body, dict): raise AnchorRecoveryError("UPSTOX_INVALID_RESPONSE")
        return body
    def option_contracts(self, underlying: str, expiry: date):
        rows = self._get("/v2/option/contract", {"instrument_key":underlying,"expiry_date":expiry.isoformat()}).get("data")
        if not isinstance(rows, list): raise AnchorRecoveryError("OPTION_CONTRACTS_INVALID")
        return rows
    def intraday_1m(self, instrument_key: str):
        encoded = quote(instrument_key, safe="")
        data = self._get(f"/v3/historical-candle/intraday/{encoded}/minutes/1").get("data")
        rows = data.get("candles") if isinstance(data, dict) else None
        if not isinstance(rows, list): raise AnchorRecoveryError("INTRADAY_CANDLES_INVALID")
        return rows

def _exact_candle(source, instrument_key: str, expected: datetime):
    out=[]
    for row in source.intraday_1m(instrument_key):
        if not isinstance(row,list) or not row: continue
        try: ts=datetime.fromisoformat(str(row[0]).replace("Z","+00:00")).astimezone(IST)
        except Exception: continue
        if ts == expected: out.append(row)
    if len(out) != 1: raise AnchorRecoveryError(f"EXACT_CANDLE_COUNT_{instrument_key}_{expected.isoformat()}_{len(out)}")
    return out[0]

def _valid_oi(v):
    if type(v) not in (int,float) or not math.isfinite(v) or v < 0 or int(v) != v: raise AnchorRecoveryError("OPTION_OI_INVALID_OR_MISSING")
    return int(v)

def _contract_index(rows, underlying: str, expiry: date):
    idx={}
    for r in rows:
        if not isinstance(r,dict): continue
        if r.get("underlying_key") not in (None,underlying) or r.get("expiry") not in (None,expiry.isoformat()): continue
        side=str(r.get("instrument_type") or r.get("option_type") or "").upper()
        side={"CALL":"CE","PUT":"PE"}.get(side,side)
        if side not in ("CE","PE"): continue
        try: strike=float(r["strike_price"])
        except Exception: continue
        key=str(r.get("instrument_key") or "").strip()
        if not key: continue
        ident=(strike,side)
        if ident in idx and idx[ident] != key: raise AnchorRecoveryError("DUPLICATE_OPTION_CONTRACT_IDENTITY")
        idx[ident]=key
    return idx

def recover_upstox_fixed_anchor(*, source, session_date: date, underlying: str, expiry: date, anchor_time="09:20", wings=5, strike_interval=50.0):
    checkpoint=_anchor_dt(session_date,anchor_time); source_minute=checkpoint-timedelta(minutes=1)
    if session_date != datetime.now(IST).date():
        return FixedSessionAnchor(MODEL,"NOT_APPLICABLE",PROV_NA,session_date.isoformat(),checkpoint.isoformat(),None,None,None,underlying,expiry.isoformat(),None,None,strike_interval,wings,(),(),None,None,None,False,"CURRENT_DAY_INTRADAY_ENDPOINT_ONLY")
    uc=_exact_candle(source,underlying,source_minute)
    if len(uc)<5: raise AnchorRecoveryError("UNDERLYING_CANDLE_INCOMPLETE")
    try: spot=float(uc[4])
    except Exception as exc: raise AnchorRecoveryError("UNDERLYING_CLOSE_INVALID") from exc
    atm=_round_half_up(spot,strike_interval)
    strikes=tuple(float(atm+i*strike_interval) for i in range(-wings,wings+1))
    idx=_contract_index(source.option_contracts(underlying,expiry),underlying,expiry)
    legs=[]
    for strike in strikes:
        for side in ("CE","PE"):
            key=idx.get((strike,side))
            label=int(strike) if strike.is_integer() else strike
            if not key: raise AnchorRecoveryError(f"EXACT_CONTRACT_MISSING_{label}_{side}")
            c=_exact_candle(source,key,source_minute)
            if len(c)<=6: raise AnchorRecoveryError(f"OPTION_OI_FIELD_MISSING_{label}_{side}")
            legs.append(FixedAnchorLeg(strike,side,key,_valid_oi(c[6])))
    expected=(2*wings+1)*2
    if len(legs)!=expected: raise AnchorRecoveryError(f"FIXED_BASKET_INCOMPLETE_{len(legs)}_OF_{expected}")
    ce=sum(x.open_interest for x in legs if x.side=="CE"); pe=sum(x.open_interest for x in legs if x.side=="PE")
    return FixedSessionAnchor(MODEL,"AVAILABLE",PROV_RECOVERED,session_date.isoformat(),checkpoint.isoformat(),source_minute.isoformat(),"COMPLETED_1M_BOUNDARY","UPSTOX",underlying,expiry.isoformat(),spot,atm,strike_interval,wings,strikes,tuple(legs),ce,pe,_pcr(pe,ce),False)

def capture_live_fixed_anchor(*, snapshot: Snapshot, session_date: date, anchor_time: str, wings: int, strike_interval=50.0):
    checkpoint=_anchor_dt(session_date,anchor_time); atm=_round_half_up(float(snapshot.spot),strike_interval)
    strikes=tuple(float(atm+i*strike_interval) for i in range(-wings,wings+1))
    catalog={(float(c.strike),c.side):c.key for c in snapshot.catalog}; quotes={q.key:q for q in snapshot.quotes}; legs=[]
    for strike in strikes:
        for side in ("CE","PE"):
            key=catalog.get((strike,side)); label=int(strike) if strike.is_integer() else strike
            if not key: raise AnchorRecoveryError(f"LIVE_EXACT_CONTRACT_MISSING_{label}_{side}")
            q=quotes.get(key)
            if q is None or q.oi is None: raise AnchorRecoveryError(f"LIVE_OPTION_OI_MISSING_{label}_{side}")
            legs.append(FixedAnchorLeg(strike,side,key,int(q.oi)))
    ce=sum(x.open_interest for x in legs if x.side=="CE"); pe=sum(x.open_interest for x in legs if x.side=="PE")
    return FixedSessionAnchor(MODEL,"AVAILABLE",PROV_LIVE,session_date.isoformat(),checkpoint.isoformat(),None,"FIRST_LIVE_SNAPSHOT_AT_OR_AFTER_CHECKPOINT_WITHIN_30S",str(snapshot.provider).upper(),snapshot.underlying,snapshot.expiry.isoformat(),float(snapshot.spot),atm,strike_interval,wings,strikes,tuple(legs),ce,pe,_pcr(pe,ce),False)

def fixed_session_metrics(*, anchor: FixedSessionAnchor, snapshot: Snapshot, checkpoint: datetime):
    if anchor.status!="AVAILABLE" or anchor.atm is None or anchor.ce_total is None or anchor.pe_total is None: raise ValueError("Fixed anchor is not available")
    quotes={q.key:q for q in snapshot.quotes}; ce=0; pe=0; missing=[]
    for leg in anchor.legs:
        q=quotes.get(leg.instrument_key)
        if q is None or q.oi is None: missing.append(leg.instrument_key); continue
        if leg.side=="CE": ce+=int(q.oi)
        else: pe+=int(q.oi)
    if missing:
        return FixedSessionMetrics("INCOMPLETE",anchor.provenance,checkpoint.astimezone(IST).isoformat(),float(anchor.atm),anchor.strikes,anchor.ce_total,anchor.pe_total,None,None,None,None,None,anchor.fixed_pcr,None,None,tuple(sorted(set(missing))))
    ced=ce-anchor.ce_total; ped=pe-anchor.pe_total; cp=_pcr(pe,ce)
    return FixedSessionMetrics("AVAILABLE",anchor.provenance,checkpoint.astimezone(IST).isoformat(),float(anchor.atm),anchor.strikes,anchor.ce_total,anchor.pe_total,ce,pe,ced,ped,ped-ced,anchor.fixed_pcr,cp,(cp-anchor.fixed_pcr) if cp is not None and anchor.fixed_pcr is not None else None,())

class FixedAnchorJournalV1:
    def __init__(self,path): self.path=Path(path)
    def append(self,payload):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("a",encoding="utf-8") as f: f.write(json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n")

class LiveFixedSessionAnchorManagerV1:
    def __init__(self,*,engine,config_id,journal_path="data/live-observation/shadow-v1/fixed-anchor.jsonl",strike_interval=50.0,live_max_delay_seconds=30):
        self.engine=engine; self.config_id=config_id; self.journal=FixedAnchorJournalV1(journal_path); self.strike_interval=strike_interval; self.live_max_delay_seconds=live_max_delay_seconds; self._session_date=None; self._anchor=None; self._last_issue=None
    def _config(self):
        from sqlalchemy.orm import Session
        from .storage import Configuration
        with Session(self.engine) as s:
            row=s.get(Configuration,self.config_id)
            if row is None: raise AnchorRecoveryError("CONFIGURATION_NOT_FOUND")
            return PCRConfig.model_validate(row.payload)
    def _local_snapshot(self,session_date,checkpoint):
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from .storage import Observation
        with Session(self.engine) as s:
            rows=s.scalars(select(Observation).where(Observation.config_id==self.config_id,Observation.session_date==session_date.isoformat()).order_by(Observation.id)).all()
        candidates=[]
        for row in rows:
            try: snap=Snapshot.model_validate(row.snapshot)
            except Exception: continue
            delay=(snap.received_at-checkpoint).total_seconds()
            if 0<=delay<=self.live_max_delay_seconds: candidates.append(snap)
        return min(candidates,key=lambda x:x.received_at) if candidates else None
    def _missing(self,config,session_date,checkpoint,issue,status="MISSING"):
        return FixedSessionAnchor(MODEL,status,PROV_NA if status=="NOT_APPLICABLE" else PROV_MISSING,session_date.isoformat(),checkpoint.isoformat(),None,None,None,config.underlying,config.expiry.isoformat(),None,None,self.strike_interval,config.wings,(),(),None,None,None,False,issue)
    def ensure(self,checkpoint):
        checkpoint=checkpoint.astimezone(IST); session_date=checkpoint.date(); config=self._config(); anchor_cp=_anchor_dt(session_date,config.anchor_time)
        if self._session_date!=session_date: self._session_date=session_date; self._anchor=None; self._last_issue=None
        if self._anchor is not None and self._anchor.status=="AVAILABLE": return self._anchor
        if session_date!=datetime.now(IST).date(): return self._missing(config,session_date,anchor_cp,"CURRENT_DAY_RECOVERY_NOT_APPLICABLE_TO_REPLAY","NOT_APPLICABLE")
        if checkpoint<anchor_cp+timedelta(seconds=self.live_max_delay_seconds): return self._missing(config,session_date,anchor_cp,"WAITING_FOR_LIVE_ANCHOR_WINDOW","PENDING")
        local=self._local_snapshot(session_date,anchor_cp)
        if local is not None:
            try:
                a=capture_live_fixed_anchor(snapshot=local,session_date=session_date,anchor_time=config.anchor_time,wings=config.wings,strike_interval=self.strike_interval); self._anchor=a; self.journal.append(a.payload()); return a
            except AnchorRecoveryError as exc: self._last_issue=str(exc)
        token=os.getenv("UPSTOX_ACCESS_TOKEN","")
        if not token:
            m=self._missing(config,session_date,anchor_cp,"UPSTOX_ACCESS_TOKEN_MISSING")
            if self._last_issue!=m.issue: self.journal.append(m.payload()); self._last_issue=m.issue
            return m
        source=None
        try:
            source=UpstoxIntradayAnchorSourceV1(token)
            a=recover_upstox_fixed_anchor(source=source,session_date=session_date,underlying=config.underlying,expiry=config.expiry,anchor_time=config.anchor_time,wings=config.wings,strike_interval=self.strike_interval)
            if a.status=="AVAILABLE": self._anchor=a; self.journal.append(a.payload())
            return a
        except AnchorRecoveryError as exc:
            issue=str(exc); m=self._missing(config,session_date,anchor_cp,issue)
            if self._last_issue!=issue: self.journal.append(m.payload()); self._last_issue=issue
            return m
        finally:
            if source is not None: source.close()
    def metrics(self,snapshot,checkpoint):
        if self._anchor is None or self._anchor.status!="AVAILABLE": return None
        return fixed_session_metrics(anchor=self._anchor,snapshot=snapshot,checkpoint=checkpoint)
