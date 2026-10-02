# MIDPOINT V3.2 — One-Shot OOS-H Final Validation V1

This bundle is the **final untouched OOS-H validation gate** for the frozen Midpoint V3.2 strategy.

## Frozen system

- Entry model: `MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2`
- Entry execution: `EXACT_NEXT_MINUTE_OPEN_AFTER_T3`
- Option contract: `EXACT_MOVING_ATM_AT_T3_NO_NEAREST_FALLBACK`
- Exit: `SL5_BE5_TRAIL3_AFTER10_TIME15`
- Cost: 0.50 percentage points round trip
- Initial stop: 5%
- Breakeven: trigger at +5%, active next bar
- Trail: activate at +10%, 3% distance, updates active next bar
- Gap-through stop: exit at bar OPEN
- Maximum hold: 15 one-minute bars

## Important sequence

Do **not fetch or inspect OOS-H first**.

### 1. Install the bundle and commit it

Copy the bundle files into the repository and commit/push them.

### 2. Run tests

```bash
python -m pytest \
  tests/test_midpoint_v3_2_oos_h_final_validation_v1.py -v
```

### 3. Create the freeze contract BEFORE opening H

Use the robustness output that already returned `ROBUSTNESS_SUPPORTIVE`.

```bash
python -m market_lab.midpoint_v3_2_oos_h_freeze_contract_v1 \
  --robustness data/historical-evidence/midpoint-v3-2-temporal-dependence-robustness-v1-development.json \
  --freeze-file backend/market_lab/midpoint_stable_feature_state_machine_v3_2.py \
  --freeze-file backend/market_lab/midpoint_v3_2_exact_option_economics_v1.py \
  --freeze-file backend/market_lab/midpoint_v3_2_oos_h_frozen_exit_replay_v1.py \
  --freeze-file backend/market_lab/midpoint_v3_2_oos_h_final_validation_v1.py \
  --output data/historical-evidence/midpoint-v3-2-oos-h-freeze-contract-v1.json
```

If the state-machine filename in your repo differs, use the actual V3.2 module path. The freeze contract hashes the exact files.

Commit the freeze contract:

```bash
git add -f data/historical-evidence/midpoint-v3-2-oos-h-freeze-contract-v1.json
git commit -m "Freeze Midpoint V3.2 system before OOS-H"
git push origin feature/pcr-foundation
```

### 4. Only now prepare OOS-H

Use a manifest that is completely non-overlapping with TRAIN/OOS-A/B/C/D and all prior OOS research.

Recommended artifact names:

```text
data/historical-validation/manifest-oos-h-20.json
data/historical-evidence/evidence-oos-h.csv
data/historical-evidence/positioning-oos-h.csv
data/historical-evidence/option-ohlc-oos-h.csv
```

Generate positioning and OHLC with the same existing sidecar tools used for earlier blocks.

### 5. Generate the H-only V3.2 signal/economics artifacts

Run the same frozen V3.2 upstream pipeline that generated the development state-machine and exact-option economics, but with `OOS_H` as the only final-validation block.

The final economics artifact must preserve:

```text
entry_rule   = EXACT_NEXT_MINUTE_OPEN_AFTER_T3
contract_rule = EXACT_MOVING_ATM_AT_T3_NO_NEAREST_FALLBACK
```

Suggested filename:

```text
data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-oos-h.json
```

Do **not** run the multi-policy exit search against H.

### 6. Apply only the frozen exit

```bash
python -m market_lab.midpoint_v3_2_oos_h_frozen_exit_replay_v1 \
  --freeze-contract data/historical-evidence/midpoint-v3-2-oos-h-freeze-contract-v1.json \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-oos-h.json \
  --ohlc data/historical-evidence/option-ohlc-oos-h.csv \
  --output data/historical-evidence/midpoint-v3-2-oos-h-frozen-exit-replay-v1.json
```

### 7. Produce the one-shot final decision

```bash
python -m market_lab.midpoint_v3_2_oos_h_final_validation_v1 \
  --freeze-contract data/historical-evidence/midpoint-v3-2-oos-h-freeze-contract-v1.json \
  --replay data/historical-evidence/midpoint-v3-2-oos-h-frozen-exit-replay-v1.json \
  --output data/historical-evidence/midpoint-v3-2-oos-h-final-validation-v1.json
```

Compact output:

```bash
jq '{
  research_version,
  block,
  frozen_policy_id,
  final_decision,
  decision_reasons,
  headline,
  direction_summaries,
  integrity_issues,
  paper_trading_status,
  live_trading_status,
  governance
}' data/historical-evidence/midpoint-v3-2-oos-h-final-validation-v1.json
```

## Predeclared decision gate

Before seeing H:

- fewer than 10 realized trades → `HOLD_INSUFFICIENT_SAMPLE`
- integrity/freeze violation → `FAIL_INTEGRITY`
- at least 10 trades, mean net > 0 and PF > 1 → `PASS_CANDIDATE_FOR_PAPER_TRADING_REVIEW`
- otherwise → `FAIL_ECONOMICS`

A PASS only makes the strategy eligible for a separate paper-trading review. It does not authorize live trading.

Once OOS-H is run, H is consumed forever as a pristine holdout. Do not retune and retest on it.
