# MIDPOINT V2 FBR Structural Stop Diagnostics V1

The E15 stop-regime attribution showed that `FAILED_BREAK_RECLAIM` has 5 genuine
INITIAL_SL5 exits, and 3 of those 5 later recovered to entry/+5.

Rather than sweep wider option-premium stops, this phase tests a structural
hypothesis derived from the strategy itself:

> A failed-break-reclaim reversal remains structurally valid while the reclaimed
> reference midpoint continues to hold on 1-minute CLOSE.

Rules:

- bullish FBR: invalidate on 1-minute CLOSE below reference midpoint;
- bearish FBR: invalidate on 1-minute CLOSE above reference midpoint;
- wick-only crossings do not invalidate.

This is diagnostic only. It does not replace SL5 or simulate P&L yet.

## Linux test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_fbr_structural_stop_diagnostics_v1.py -v
```

Expected: 2 tests.

## Run

```bash
python -m market_lab.midpoint_v2_fbr_structural_stop_diagnostics_v1 \
  --structural data/historical-evidence/midpoint-v2-structural-reconstruction-v1-development.json \
  --economics data/historical-evidence/midpoint-v2-new-arm-exact-option-economics-v1-development.json \
  --attribution data/historical-evidence/midpoint-v2-e15-stop-regime-attribution-v1-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-fbr-structural-stop-diagnostics-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  candidate_scope,
  candidate_count,
  hypothesis,
  overall_summary,
  direction_summaries,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-fbr-structural-stop-diagnostics-v1-development.json
```

## Interpretation

The key comparison is among the 5 genuine FBR INITIAL_SL5 exits:

- Did the 3 later-recovering trades keep the reclaimed midpoint structurally valid?
- Did the 2 non-recovering trades lose the midpoint early?

If that separation appears, the next step can be a single, predeclared
FBR-specific structural-stop replay.

If it does not separate recoverers from non-recoverers, do not promote it and
return to entry-quality research rather than widening arbitrary premium stops.
