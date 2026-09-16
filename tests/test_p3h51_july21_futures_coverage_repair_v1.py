import csv
from pathlib import Path
from market_lab.p3h51_july21_futures_coverage_repair_v1 import REQUIRED_COLUMNS, merge_patch

def write_rows(path: Path, rows):
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=REQUIRED_COLUMNS)
        w.writeheader()
        w.writerows(rows)

def row(day, minute, key="FUT"):
    return {
        "session_date": day, "expiry": "2026-07-28", "instrument_key": key,
        "trading_symbol": "NIFTY FUT 28 JUL 26", "contract_source": "EXPIRED_FUTURE_API",
        "timestamp": f"{day}T{minute}:00+05:30", "open":"25000","high":"25010",
        "low":"24990","close":"25005","volume":"100","open_interest":"1000",
        "typical_price":"25001.6667","session_cumulative_volume":"100","session_vwap":"25001.6667",
    }

def test_merge_replaces_only_target_date(tmp_path):
    base, patch, out = tmp_path/"base.csv", tmp_path/"patch.csv", tmp_path/"out.csv"
    write_rows(base, [row("2026-07-20","09:15"), row("2026-07-22","09:15")])
    patch_rows = []
    for h in range(9,16):
        for m in range(60):
            if h == 9 and m < 15: continue
            if h == 15 and m > 29: continue
            patch_rows.append(row("2026-07-21", f"{h:02d}:{m:02d}"))
    write_rows(patch, patch_rows)
    result = merge_patch(base_csv=base, patch_csv=patch, output_csv=out)
    assert result["base_target_rows_before"] == 0
    assert result["patch_rows"] == len(patch_rows)
    with out.open(newline="") as h:
        rows = list(csv.DictReader(h))
    assert any(r["session_date"] == "2026-07-20" for r in rows)
    assert any(r["session_date"] == "2026-07-21" for r in rows)
    assert any(r["session_date"] == "2026-07-22" for r in rows)
