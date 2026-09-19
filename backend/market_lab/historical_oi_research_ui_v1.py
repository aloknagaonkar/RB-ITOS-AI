from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

MODEL = "HISTORICAL_OI_RESEARCH_UI_V1"
DEFAULT_SOURCE = Path("data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv")
NUMERIC_FIELDS = {"spot","moving_atm","fixed_atm","m_ce_oi","m_pe_oi","m_ce_delta","m_pe_delta","m_ce_pct","m_pe_pct","m_activity","m_pcr_previous","m_pcr","m_pcr_change","atm_ce_price_pct","atm_pe_price_pct","f_ce_delta","f_pe_delta","f_activity","f_pcr","forward_5m_points","forward_10m_points","forward_15m_points"}

def _coerce(row: dict[str,str]) -> dict[str,Any]:
    out=dict(row)
    for key in NUMERIC_FIELDS:
        value=out.get(key)
        if value in (None,""):
            out[key]=None
            continue
        try:
            out[key]=float(value)
        except (TypeError,ValueError):
            pass
    return out

def load_rows(source: str|Path = DEFAULT_SOURCE) -> list[dict[str,Any]]:
    path=Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Historical OI research source not found: {path}")
    with path.open(newline="",encoding="utf-8") as handle:
        return [_coerce(row) for row in csv.DictReader(handle)]

def inventory(source: str|Path = DEFAULT_SOURCE) -> dict[str,Any]:
    rows=load_rows(source)
    by_date={}
    for row in rows:
        d=str(row.get("session_date") or "")
        if d:
            by_date[d]=by_date.get(d,0)+1
    dates=sorted(by_date,reverse=True)
    return {"model":MODEL,"source":str(source),"session_count":len(dates),"row_count":len(rows),"first_session":min(dates) if dates else None,"last_session":max(dates) if dates else None,"sessions":[{"session_date":d,"rows":by_date[d]} for d in dates]}

def session_rows(session_date: str, source: str|Path = DEFAULT_SOURCE) -> dict[str,Any]:
    rows=[r for r in load_rows(source) if r.get("session_date")==session_date]
    rows.sort(key=lambda r:str(r.get("timestamp") or r.get("time") or ""))
    if not rows:
        raise KeyError(f"No historical OI research rows for {session_date}")
    return {"model":MODEL,"source":str(source),"session_date":session_date,"row_count":len(rows),"block":rows[0].get("block"),"rows":rows}
