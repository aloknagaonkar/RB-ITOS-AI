# MIDPOINT V2 New-Arm Exact Option Economics V1

This phase evaluates ONLY the 17 genuinely new V2 structural candidates:

- 8 `BASE_THEN_GO`
- 9 `FAILED_BREAK_RECLAIM`

It deliberately excludes all `IMMEDIATE_CONTINUATION` rows.

## Execution semantics

For each new V2 candidate:

1. Take `entry_direction` from `v2_result`.
2. Map:
   - BULLISH -> CE
   - BEARISH -> PE
3. Use `confirmation_timestamp`, not original T+3.
4. Select exact moving ATM at that confirmation timestamp.
5. No nearest-time or nearest-strike fallback.
6. Enter exact next-minute OPEN.
7. Compute 1m / 3m / 5m / 10m / 15m net returns and 15m MFE/MAE.
8. Do NOT select an exit policy in this phase.

## Linux test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_new_arm_exact_option_economics_v1.py -v
```

## Input filenames

Use the same development positioning and option-OHLC sidecars used by V1.
If your filenames differ from the examples below, substitute the actual existing paths.

Example run:

```bash
python -m market_lab.midpoint_v2_new_arm_exact_option_economics_v1 \
  --structural data/historical-evidence/midpoint-v2-structural-reconstruction-v1-development.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-new-arm-exact-option-economics-v1-development.json
```

## Compact result

```bash
jq '{
  research_version,
  candidate_scope,
  entry_rule,
  contract_rule,
  candidate_count,
  arm_counts,
  direction_counts,
  instrument_available_count,
  entry_available_count,
  complete_15m_path_count,
  overall_summary,
  arm_summaries,
  direction_summaries,
  block_summaries,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-new-arm-exact-option-economics-v1-development.json
```

## Gate before exit-duration research

We first require:
- candidate_count = 17
- BASE_THEN_GO = 8
- FAILED_BREAK_RECLAIM = 9
- all 17 have confirmation timestamps (already validated structurally)
- investigate any unavailable exact ATM / entry / path as data issues, never substitute
- no OOS-H
- no immediate-continuation mixing

After this economics inventory is accepted, the next isolated phase compares the frozen V1 exit against:
- E15 baseline
- HYBRID: time-15 unless trail active
- E20
- E30
- continuous trail with safety cap
