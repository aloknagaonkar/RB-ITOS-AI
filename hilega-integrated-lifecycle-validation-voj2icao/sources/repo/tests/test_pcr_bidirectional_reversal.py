import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from market_lab.pcr_bidirectional_reversal import analyze_bidirectional_blocks

TZ = timezone(timedelta(hours=5, minutes=30))


def _write(path: Path):
    fields = [
        "session_date", "timestamp", "spot",
        "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m",
        "forward_change_5m", "forward_change_10m", "forward_change_15m", "forward_change_30m",
    ]
    start = datetime(2026, 1, 1, 9, 15, tzinfo=TZ)
    rows=[]
    # Build enough exact minute history. Spot rises, then after bearish S2 turns down.
    for i in range(80):
        dt=start+timedelta(minutes=i)
        spot=100.0+i*0.2
        if i>=40:
            spot=108.0-(i-40)*0.3
        s5=s15=s30=0.1
        # bearish Stage2 first entry at minute 35
        if i in (35,36): s5,s15,s30=-0.1,-0.2,0.3
        # bullish Stage2 first entry at minute 55, after price has been declining
        if i in (55,56): s5,s15,s30=0.1,0.2,-0.3
        def future(n):
            j=i+n
            if j>=80: return ""
            fspot = 100.0+j*0.2 if j<40 else 108.0-(j-40)*0.3
            return fspot-spot
        rows.append({
            "session_date":"2026-01-01", "timestamp":dt.isoformat(), "spot":spot,
            "moving_pcr_change_5m":s5, "moving_pcr_change_15m":s15, "moving_pcr_change_30m":s30,
            "forward_change_5m":future(5), "forward_change_10m":future(10),
            "forward_change_15m":future(15), "forward_change_30m":future(30),
        })
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def test_analyzes_both_directions(tmp_path):
    path=tmp_path/"evidence.csv"; _write(path)
    report=analyze_bidirectional_blocks([("TRAIN", path)])
    assert report.status == "AVAILABLE"
    assert report.bearish.blocks[0].stage_2_event_count == 1
    assert report.bullish.blocks[0].stage_2_event_count == 1
    assert "5m and 15m falling" in report.bearish.stage_2_definition
    assert "5m and 15m rising" in report.bullish.stage_2_definition


def test_persistent_stage2_is_deduplicated(tmp_path):
    path=tmp_path/"evidence.csv"; _write(path)
    report=analyze_bidirectional_blocks([("TRAIN", path)])
    assert report.bearish.combined.event_count == 1
    assert report.bullish.combined.event_count == 1


def test_multiple_blocks_are_kept_independent(tmp_path):
    paths=[]
    for name in ("TRAIN","OOS_A","OOS_B","OOS_C","OOS_D"):
        p=tmp_path/f"{name}.csv"; _write(p); paths.append((name,p))
    report=analyze_bidirectional_blocks(paths)
    assert report.block_count == 5
    assert len(report.bearish.blocks) == 5
    assert len(report.bullish.blocks) == 5
    assert report.total_row_count == 400
