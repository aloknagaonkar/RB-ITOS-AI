# MIDPOINT V2 Stop-Path Diagnostics V1

The exit-duration study showed that extending time did not help:

- E15 and HYBRID were identical because no trade had an active trail at 15m.
- E20, E30, and TRAIL_ONLY degraded progressively.

Therefore this phase does NOT test another duration rule and does NOT search SL6/SL7/SL8.

Instead it asks whether the existing 5% stop is structurally compatible with the two new V2 arms.

## Diagnostics

For each of the 17 new-arm trades:

- first minute the existing -5% stop was hit;
- gap vs touch;
- maximum favorable move before stop;
- after the stop bar, whether the same contract:
  - recovered to entry;
  - reached +5%;
  - reached +10%;
  - finished net-positive at 15m;
- 15m final result among stop-hit trades.

Post-stop analysis starts on the NEXT bar. If a bar contains both the stop and +5/+10 high, it is marked ambiguous; intrabar sequencing is not invented.

## Linux test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_midpoint_v2_stop_path_diagnostics_v1.py -v
```

Expected: 3 tests.

## Run

```bash
python -m market_lab.midpoint_v2_stop_path_diagnostics_v1   --economics data/historical-evidence/midpoint-v2-new-arm-exact-option-economics-v1-development.json   --ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv'   --ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv'   --ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv'   --ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv'   --ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv'   --output data/historical-evidence/midpoint-v2-stop-path-diagnostics-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  candidate_count,
  diagnostic_stop_pct,
  reference_trigger_levels_pct,
  overall_summary,
  arm_summaries,
  direction_summaries,
  integrity,
  governance
}' data/historical-evidence/midpoint-v2-stop-path-diagnostics-v1-development.json
```

## Interpretation

If most stop-hit trades remain bad afterwards, SL5 is doing useful loss containment and the problem is likely entry quality.

If many stop-hit trades recover to entry / +5 / +10 or finish positive at 15m, then the new arm may have a different adverse-excursion profile from frozen V1. That would justify defining a SINGLE predeclared stop hypothesis for later development testing—not sweeping many thresholds.

This module does not promote any stop or arm.
