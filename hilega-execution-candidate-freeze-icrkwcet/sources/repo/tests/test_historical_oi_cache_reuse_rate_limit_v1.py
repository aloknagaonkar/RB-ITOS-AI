import json
from pathlib import Path

from market_lab.historical_oi_cache_reuse_rate_limit_v1 import find_verified_existing_source

def _write(path: Path, date: str, expiry: str, wings: int, valid=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ce_instrument_key":"CE1" if valid else None,
        "pe_instrument_key":"PE1" if valid else None,
        "ce_open_interest":100 if valid else None,
        "pe_open_interest":120 if valid else None,
    }
    path.write_text(json.dumps({"sessions":[{
        "session_date":date,"expiry":expiry,"status":"AVAILABLE",
        "wings":wings,"row_count":1,"rows":[row],
    }]}))

def test_reuses_verified_legacy_cache(tmp_path):
    p=tmp_path/"data/historical-positioning-cache-oos-c"/"NSE_INDEX_Nifty_50__2026-06-03__2026-06-09__w5.json"
    _write(p,"2026-06-03","2026-06-09",5)
    got=find_verified_existing_source("2026-06-03","2026-06-09",min_wings=5,repo_root=tmp_path)
    assert got == p

def test_rejects_available_shell(tmp_path):
    p=tmp_path/"data/historical-positioning-cache-x"/"NSE_INDEX_Nifty_50__2026-06-03__2026-06-09__w5.json"
    _write(p,"2026-06-03","2026-06-09",5,valid=False)
    assert find_verified_existing_source("2026-06-03","2026-06-09",min_wings=5,repo_root=tmp_path) is None

def test_prefers_narrowest_adequate_existing_width(tmp_path):
    p7=tmp_path/"data/historical-positioning-cache-x"/"A__2026-06-03__2026-06-09__w7.json"
    p10=tmp_path/"data/historical-positioning-cache-y"/"B__2026-06-03__2026-06-09__w10.json"
    _write(p7,"2026-06-03","2026-06-09",7)
    _write(p10,"2026-06-03","2026-06-09",10)
    got=find_verified_existing_source("2026-06-03","2026-06-09",min_wings=6,repo_root=tmp_path)
    assert got == p7
