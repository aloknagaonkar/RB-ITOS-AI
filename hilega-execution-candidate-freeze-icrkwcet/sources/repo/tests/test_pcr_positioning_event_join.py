import csv
import json
from pathlib import Path

from market_lab.pcr_positioning_event_join import analyze


def _write(path: Path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def test_join_finds_bearish_confirmation_at_t_plus_2(tmp_path):
    ev = tmp_path / "e.csv"
    pos = tmp_path / "p.csv"
    fields = ["session_date","timestamp","spot","moving_pcr_change_5m","moving_pcr_change_15m","moving_pcr_change_30m","forward_change_5m","forward_change_15m","forward_change_30m"]
    rows=[]
    for m in range(0, 33):
        ts=f"2026-01-01T09:{15+m:02d}:00+05:30"
        if m == 30:
            signs=(-1,-1,1)
        else:
            signs=(1,1,1)
        rows.append(dict(session_date="2026-01-01",timestamp=ts,spot=100+m,moving_pcr_change_5m=signs[0],moving_pcr_change_15m=signs[1],moving_pcr_change_30m=signs[2],forward_change_5m=-1,forward_change_15m=-2,forward_change_30m=-3))
    _write(ev, fields, rows)
    pfields=["session_date","timestamp","strike","strike_offset","combined_5m","ce_5m_state","pe_5m_state"]
    prows=[]
    for off in range(6):
        prows.append(dict(session_date="2026-01-01",timestamp=f"2026-01-01T09:{45+off:02d}:00+05:30",strike="100",strike_offset="0",combined_5m="STRONG_BEARISH" if off==2 else "MIXED",ce_5m_state="SHORT_BUILDUP",pe_5m_state="LONG_BUILDUP"))
    _write(pos,pfields,prows)
    result=analyze(ev,pos)
    b=result["directions"]["bearish"]
    assert b["stage_2_event_count"] == 1
    assert b["confirmed_within_5m_count"] == 1
    assert b["first_confirmation_offset_counts"] == {"2": 1}
