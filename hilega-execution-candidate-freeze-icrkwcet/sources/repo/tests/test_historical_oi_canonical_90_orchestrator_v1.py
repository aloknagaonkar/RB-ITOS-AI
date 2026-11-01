import csv
import json
from pathlib import Path

from market_lab.historical_oi_canonical_90_orchestrator_v1 import (
    canonical_dates,
    resolve_exact_expiry,
)

def _write_cache(path: Path, date: str, expiry: str, status="AVAILABLE"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version":1,
        "status":status,
        "session_date":date,
        "expiry":expiry,
        "wings":5,
        "rows":[{
            "ce_instrument_key":"CE1",
            "pe_instrument_key":"PE1",
            "ce_open_interest":100,
            "pe_open_interest":120,
        }]
    }))

def test_canonical_dates_unique(tmp_path):
    p=tmp_path/"canonical.csv"
    p.write_text("session_date,time\n2026-05-04,09:20\n2026-05-04,09:25\n2026-05-05,09:20\n")
    assert canonical_dates(p)==["2026-05-04","2026-05-05"]

def test_exact_expiry_resolves_from_quality_cache(tmp_path):
    root=tmp_path/"data"
    p=root/"historical-positioning-cache-oos-a"/"NSE_INDEX_Nifty_50__2026-05-04__2026-05-05__w5.json"
    _write_cache(p,"2026-05-04","2026-05-05")
    r=resolve_exact_expiry("2026-05-04",build_root=root/"historical-evidence"/"historical-oi-build",data_root=root)
    assert r["status"]=="RESOLVED"
    assert r["expiry"]=="2026-05-05"

def test_shell_or_unavailable_not_accepted(tmp_path):
    root=tmp_path/"data"
    p=root/"historical-positioning-cache-x"/"NSE_INDEX_Nifty_50__2026-05-04__2026-05-05__w5.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({
        "status":"AVAILABLE","session_date":"2026-05-04","expiry":"2026-05-05",
        "rows":[{"ce_instrument_key":None,"pe_instrument_key":None,"ce_open_interest":None,"pe_open_interest":None}]
    }))
    r=resolve_exact_expiry("2026-05-04",build_root=root/"historical-evidence"/"historical-oi-build",data_root=root)
    assert r["status"]=="EXPIRY_REQUIRED"

def test_conflicting_expiries_are_ambiguous(tmp_path):
    root=tmp_path/"data"
    a=root/"historical-positioning-cache-a"/"NSE_INDEX_Nifty_50__2026-05-04__2026-05-05__w5.json"
    b=root/"historical-positioning-cache-b"/"NSE_INDEX_Nifty_50__2026-05-04__2026-05-12__w5.json"
    _write_cache(a,"2026-05-04","2026-05-05")
    _write_cache(b,"2026-05-04","2026-05-12")
    r=resolve_exact_expiry("2026-05-04",build_root=root/"historical-evidence"/"historical-oi-build",data_root=root)
    assert r["status"]=="EXPIRY_AMBIGUOUS"
    assert r["candidate_expiries"]==["2026-05-05","2026-05-12"]
