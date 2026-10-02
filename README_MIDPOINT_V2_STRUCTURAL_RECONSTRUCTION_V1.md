# MIDPOINT V2 Structural Reconstruction V1

This phase uses the now-confirmed framework schema plus the existing 1-minute
underlying OHLC to reconstruct the two new V2 arms without P&L.

## Why underlying OHLC is required

The framework contains checkpoint snapshots, not every post-T+3 minute.
`BASE_THEN_GO` and `FAILED_BREAK_RECLAIM` require sequential CLOSE behavior,
so this module reads the development 1-minute underlying files after T+3.

## What stays unchanged

- V1 `CONFIRM_CONTINUATION` -> `IMMEDIATE_CONTINUATION`
- frozen TRAIN-only T+3 rules are loaded, not rederived
- OOS-H is forbidden
- no option economics
- no exit-policy research
- no paper/live orders

## Copy files

- `backend/market_lab/midpoint_v2_structural_reconstruction_v1.py`
- `tests/test_midpoint_v2_structural_reconstruction_v1.py`

## Focused test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_research_foundation_v1.py \
  tests/test_midpoint_v2_structural_reconstruction_v1.py -v
```

## Run structural reconstruction

```bash
python -m market_lab.midpoint_v2_structural_reconstruction_v1 \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --frozen-state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-structural-reconstruction-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  blocks,
  config,
  structural_event_count,
  t3_state_counts,
  v2_final_state_counts,
  entry_arm_counts,
  direction_arm_counts,
  block_arm_counts,
  missing_post_t3_minute_data_count,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-structural-reconstruction-v1-development.json
```

## Stop after this

Do NOT run V2 option P&L yet.

First inspect:
- how many WAIT_BASE cases become BASE_THEN_GO;
- how many WAIT_BASE cases transition into reclaim;
- how many RECLAIM_WATCH cases actually reclaim the midpoint and confirm opposite acceptance;
- whether the behavior is spread across TRAIN/OOS blocks and both directions;
- whether minute data coverage is complete.

Only after the structural inventory is accepted should exact option economics be added.
