# MIDPOINT_OI_VWAP_CONTROLLED_COMPARISON_V1

Two development-only arms:

- `ARM_A_OI_VWAP_5MIN`
- `ARM_C_MIDPOINT_PLUS_OI_VWAP`

There is intentionally **no Arm B / midpoint-only arm**.

## Governance

Allowed: `TRAIN`, `OOS_A`, `OOS_B`, `OOS_C`, `OOS_D`.
Forbidden: `OOS_E`, `OOS_F`, `OOS_G`, `OOS_H`.

No new thresholds, no VWAP-distance threshold, no extra indicators, no nearest strike/time fallback, no order emission.

## Arm A

Evaluate only synchronized completed 5-minute checkpoints.

- Bullish: CE `LONG_BUILDUP` + PE `SHORT_BUILDUP` + Futures close > session VWAP.
- Bearish: CE `SHORT_BUILDUP` + PE `LONG_BUILDUP` + Futures close < session VWAP.
- Persistent same-direction confluence does not duplicate.
- Neutral resets; direct direction flip emits a new signal.
- Exact moving ATM from `strike_offset == 0`.
- Entry: next 1-minute option OPEN.
- Cost: 0.5 percentage points.

## Arm C

Reuse existing leakage-safe midpoint `CONFIRM_CONTINUATION` rows. At each midpoint confirmation, use only the latest completed synchronized 5-minute checkpoint. Example: midpoint confirmation 09:28 -> use 09:25 OI/VWAP. Never use 09:30.

Arm C survives only when midpoint direction and OI/VWAP direction agree. Entry is the next 1-minute option OPEN after midpoint confirmation.

## Tests

```bash
source .venv/bin/activate
python -m pytest \
  tests/test_oi_futures_vwap_standalone_v1_5min.py \
  tests/test_midpoint_oi_vwap_controlled_comparison_v1.py -v
```

## Arm A run

```bash
python -m market_lab.oi_futures_vwap_standalone_v1_5min \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --option-ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --option-ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --option-ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --option-ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --option-ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  --output data/historical-evidence/oi-futures-vwap-standalone-v1-5min-development.json
```

## Controlled comparison

```bash
python -m market_lab.midpoint_oi_vwap_controlled_comparison_v1 \
  --arm-a data/historical-evidence/oi-futures-vwap-standalone-v1-5min-development.json \
  --midpoint data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --option-ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --option-ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --option-ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --option-ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --option-ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  --output data/historical-evidence/midpoint-oi-vwap-controlled-comparison-v1-development.json
```

Compare trade count, bullish/bearish split, 1/3/5/10/15m net returns, win rate, mean/median, PF, cumulative percentage points, TRAIN/OOS_A-D consistency, and Arm C survival percentage versus Arm A.
