import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_oi_event_boundary_v1.py"
spec = importlib.util.spec_from_file_location("analyze_oi_event_boundary_v1", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def record(seq, time, ce, pe, prior_ce, prior_pe, spot):
    ce_delta = ce - prior_ce
    pe_delta = pe - prior_pe
    prior_pcr = prior_pe / prior_ce
    current_pcr = pe / ce
    return {
        "sequence": seq,
        "checkpoint": f"2026-09-21T{time}:00+05:30",
        "stage": "NORMALIZED_FEATURES",
        "payload": {
            "spot": spot,
            "moving_atm": 23400,
            "moving_strikes": [23150,23200,23250,23300,23350,23400,23450,23500,23550,23600,23650],
            "all3_state": "MIXED",
            "horizons": {
                "5m": {
                    "state": "BULLISH" if pe_delta-ce_delta > 0 and current_pcr-prior_pcr > 0 else "BEARISH",
                    "current_ce_oi": ce,
                    "current_pe_oi": pe,
                    "prior_ce_oi": prior_ce,
                    "prior_pe_oi": prior_pe,
                    "ce_delta": ce_delta,
                    "pe_delta": pe_delta,
                    "imbalance": pe_delta-ce_delta,
                    "prior_pcr": prior_pcr,
                    "current_pcr": current_pcr,
                    "pcr_change": current_pcr-prior_pcr,
                }
            },
        },
    }


def test_cumulative_change_from_exact_pre_event_baseline(tmp_path):
    path = tmp_path / "step-audit.jsonl"
    rows = [
        record(1, "10:30", 100.0, 120.0, 90.0, 125.0, 23360),
        record(2, "10:35", 110.0, 115.0, 100.0, 120.0, 23363),
        record(3, "10:40", 130.0, 110.0, 110.0, 115.0, 23366),
        record(4, "10:45", 135.0, 120.0, 130.0, 110.0, 23380),
        record(5, "10:50", 136.0, 130.0, 135.0, 120.0, 23378),
        record(6, "10:55", 125.0, 145.0, 136.0, 130.0, 23389),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    records = mod._latest_normalized_rows(path, "2026-09-21")
    extracted = mod._extract_rows(records)
    baseline = mod._exact_row(extracted, "10:35", "baseline")
    mod._add_baseline_changes(extracted, baseline, "10:35", "10:40")

    by_time = {row["time"]: row for row in extracted}
    assert by_time["10:35"]["phase"] == "PRE_EVENT_BASELINE"
    assert by_time["10:40"]["phase"] == "EVENT"
    assert by_time["10:55"]["phase"] == "POST_EVENT"
    assert by_time["10:55"]["ce_change_from_baseline"] == 15.0
    assert by_time["10:55"]["pe_change_from_baseline"] == 30.0
    assert by_time["10:55"]["cumulative_imbalance_from_baseline"] == 15.0
    assert by_time["10:40"]["ce_delta_5m"] == 20.0
    assert by_time["10:40"]["pe_delta_5m"] == -5.0


def test_latest_sequence_wins_for_duplicate_checkpoint(tmp_path):
    path = tmp_path / "step-audit.jsonl"
    old = record(1, "10:35", 100.0, 100.0, 90.0, 90.0, 1)
    new = record(3, "10:35", 120.0, 130.0, 110.0, 120.0, 2)
    path.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n")
    records = mod._latest_normalized_rows(path, "2026-09-21")
    extracted = mod._extract_rows(records)
    assert len(extracted) == 1
    assert extracted[0]["current_ce_oi"] == 120.0
    assert extracted[0]["spot"] == 2.0
