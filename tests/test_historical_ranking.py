import csv
from pathlib import Path

from market_lab.historical_ranking import (
    MIN_ROWS_FOR_RANKING,
    build_historical_ranking_report,
    rank_historical_evidence_csv,
)


def _row(session, i, moving, fixed, full, oi, forward):
    return {
        "session_date": session,
        "timestamp": f"{session}T10:{i%60:02d}:00+05:30",
        "moving_pcr_change_15m": moving,
        "fixed_pcr_change_15m": fixed,
        "full_pcr_change_15m": full,
        "moving_oi_imbalance_pct": oi,
        "fixed_oi_imbalance_pct": oi,
        "fixed_moving_pcr_spread": moving-fixed,
        "atm_divergence_points": -50.0 if moving < 0 else 50.0,
        "forward_change_5m": forward/3,
        "forward_change_10m": forward/2,
        "forward_change_15m": forward,
        "forward_change_30m": forward*1.5,
    }


def test_baseline_adjusted_ranking_finds_cross_session_falling_condition():
    rows=[]
    for s in range(10):
        session=f"2026-08-{s+1:02d}"
        for i in range(30):
            if i < 15:
                rows.append(_row(session,i,-0.10,-0.09,-0.08,-3.0,-8.0))
            else:
                rows.append(_row(session,i,0.08,0.07,0.06,3.0,2.0))
    report=build_historical_ranking_report(rows,"fixture.csv")
    assert report.status == "AVAILABLE"
    assert report.session_count == 10
    ranked=[item for item in report.ranked_conditions if item.rank is not None]
    assert ranked
    bearish=next(item for item in ranked if item.condition_id=="PCR_ALL_FALL")
    assert bearish.row_count >= MIN_ROWS_FOR_RANKING
    out=bearish.forwards["forward_change_15m"]
    assert out.observed_direction == "BEARISH"
    assert out.adjusted_mean < 0
    assert out.directional_session_pct == 100.0


def test_small_conditions_are_not_ranked():
    rows=[_row("2026-08-01",i,-0.1,-0.1,-0.1,-2,-5) for i in range(20)]
    report=build_historical_ranking_report(rows,"fixture.csv")
    assert all(item.rank is None for item in report.ranked_conditions)


def test_csv_entrypoint(tmp_path: Path):
    path=tmp_path/"evidence.csv"
    fieldnames=[
        "session_date","timestamp","moving_pcr_change_15m","fixed_pcr_change_15m",
        "full_pcr_change_15m","moving_call_oi_change_pct","moving_put_oi_change_pct",
        "fixed_call_oi_change_pct","fixed_put_oi_change_pct","full_call_oi_change_pct",
        "full_put_oi_change_pct","fixed_moving_pcr_spread","atm_divergence_points",
        "forward_change_5m","forward_change_10m","forward_change_15m","forward_change_30m",
    ]
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fieldnames); w.writeheader()
        for s in range(8):
            for i in range(15):
                row=_row(f"2026-08-{s+1:02d}",i,-0.1,-0.1,-0.1,-2,-4)
                row.update({
                    "moving_call_oi_change_pct":3,"moving_put_oi_change_pct":1,
                    "fixed_call_oi_change_pct":3,"fixed_put_oi_change_pct":1,
                    "full_call_oi_change_pct":3,"full_put_oi_change_pct":1,
                })
                w.writerow({k:row.get(k,"") for k in fieldnames})
    report=rank_historical_evidence_csv(path)
    assert report.row_count == 120
    assert report.session_count == 8
    assert len(report.ranked_conditions) == 18
