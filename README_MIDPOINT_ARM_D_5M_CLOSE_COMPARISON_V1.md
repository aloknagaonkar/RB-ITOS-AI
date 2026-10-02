# MIDPOINT_ARM_D_5M_CLOSE_OI_VWAP_COMPARISON_V1

Controlled development-only comparison for the proposed Arm D:

`MIDPOINT_5M_CLOSE_PLUS_OI_VWAP`

Arm D deliberately removes T+3 feature scoring from the entry confirmation path.

## Frozen candidate rule

After an existing original-direction 1-minute boundary break:

- RED / bearish: wait for the **first fully completed 5-minute candle after the boundary break** and require its close below the original RED midpoint.
- GREEN / bullish: mirror rule, requiring the close above the original GREEN midpoint.
- At that same 5-minute checkpoint require exact OI + NIFTY-futures-VWAP alignment.
- Exact moving ATM at signal time.
- Next-minute OPEN entry.
- Passive 1/3/5/10/15m returns, 0.5 percentage-point cost.
- No nearest strike/time fallback.
- No E/F/G/H.
- No tuning and no rule promotion.

A 09:25 checkpoint represents the already completed 09:20–09:24 price candle. This avoids using the still-forming 09:25 minute in the 5-minute acceptance decision.

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_arm_d_5m_close_comparison_v1.py -v

python -m market_lab.midpoint_arm_d_5m_close_comparison_v1 \
  --existing-comparison data/historical-evidence/midpoint-oi-vwap-controlled-comparison-v1-development.json \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
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
  --output data/historical-evidence/midpoint-arm-d-5m-close-comparison-v1-development.json
```

Then inspect:

```bash
jq '{
  research_version,
  candidate_event_count,
  rules,
  comparison,
  arm_d: .arm_d.summary,
  arm_d_by_direction: .arm_d.by_direction,
  arm_d_by_block: .arm_d.by_block,
  diagnostic_counts,
  issue_counts,
  integrity
}' \
data/historical-evidence/midpoint-arm-d-5m-close-comparison-v1-development.json
```
