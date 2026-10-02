# MIDPOINT V2 RED MIDPOINT STRUCTURAL STOP V1

Purpose: test one question only:

> Is frozen V1's 5% option-premium stop cutting otherwise valid bearish
> structures too early?

This is NOT a V1 change. V1 remains frozen.

## Candidate population

Leakage-safe V3.2 events only:

- TRAIN
- OOS_A
- OOS_B
- OOS_C
- OOS_D
- `RED_BREAK`
- `BEARISH`
- `CONFIRM_CONTINUATION`

No legacy future outcome label is used.
E/F/G/H are forbidden.

## A/B comparison

A — Frozen V1:
`SL5_BE5_TRAIL3_AFTER10_TIME15`

B — Experimental structural stop:
- same entry
- same exact PE contract
- no premium SL5
- no premium BE
- no premium trailing
- bearish structure remains valid while 1m underlying CLOSE <= original RED midpoint
- first 1m CLOSE > original RED midpoint invalidates
- structural exit executes at exact next-minute option OPEN
- wick-only midpoint touch does not invalidate
- if no invalidation, hard exit at +15m option CLOSE
- same 0.5 percentage-point round-trip cost

This deliberately isolates structural invalidation versus premium-path stops.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_red_midpoint_structural_stop_v1.py -v
```

Expected: 3 passed.

## Run

```bash
python -m market_lab.midpoint_v2_red_midpoint_structural_stop_v1 \
  --state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --exit-research data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --option-ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --option-ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --option-ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --option-ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --option-ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-red-midpoint-structural-stop-v1-development.json
```

## Compact result

```bash
jq '{
  research_version,
  candidate_scope,
  comparison,
  summary,
  initial_sl5_subset,
  block_summaries,
  sep7_reference,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-red-midpoint-structural-stop-v1-development.json
```

Interpretation discipline:
- do not tune midpoint location after result;
- do not add a hidden premium-loss cap after seeing MAE;
- do not change time15;
- do not change entry;
- do not add OI filters;
- first read the raw A/B result exactly as predeclared.
