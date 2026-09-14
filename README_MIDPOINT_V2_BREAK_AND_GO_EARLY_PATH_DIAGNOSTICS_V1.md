# MIDPOINT V2 Break-and-Go Early Path Diagnostics V1

This phase answers one question:

Can frozen bearish `CONFIRM_CONTINUATION` events be separated descriptively into
immediate follow-through, delayed follow-through, and failed continuation
without tuning option stops or inventing an OI filter?

The path taxonomy uses only the sign of underlying close movement:

- `IMMEDIATE_FOLLOW_THROUGH`: +5m bearish favorable close movement > 0
- `DELAYED_FOLLOW_THROUGH`: +5m <= 0, but +30m or +60m > 0
- `FAILED_CONTINUATION`: +5m <= 0 and neither +30m nor +60m > 0

No optimized point threshold is used.

For each group the study compares:
- T+1 and T+3 OI quality
- exact OI transition
- 5/6 vs 6/6 price-pass count
- T+3 acceptance
- directional momentum
- progress
- giveback
- consecutive closes
- velocity
- underlying 60m MFE/MAE
- option 15m MFE/MAE descriptively only

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_early_path_diagnostics_v1.py -v
```

Expected: 4 passed.

## Run

```bash
python -m market_lab.midpoint_v2_break_and_go_early_path_diagnostics_v1 \
  --state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --checkpoint-diagnostics data/historical-evidence/midpoint-failure-diagnostics-v2-2-development.json \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-break-and-go-early-path-diagnostics-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  candidate_scope,
  path_taxonomy,
  overall,
  group_summaries,
  sep7_reference,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-break-and-go-early-path-diagnostics-v1-development.json
```

## Decision rule

Do not promote a delayed-entry rule from this diagnostic alone.

A next replay is justified only if delayed-follow-through cases show a coherent
pre-entry or immediate-post-confirmation structural signature that is materially
different from failed-continuation cases.

Do not:
- sweep SL6/7/8;
- create a bullish/bearish direction filter;
- create a new OI hard filter;
- use OOS-H, E, F, or G.
