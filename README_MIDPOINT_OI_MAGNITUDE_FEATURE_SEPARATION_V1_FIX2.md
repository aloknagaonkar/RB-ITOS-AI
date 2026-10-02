# MIDPOINT_OI_MAGNITUDE_FEATURE_SEPARATION_V1_FIX2

FIX2 addresses the zero-row bug.

The global exemplar event schema has:
- `quality_bucket` at event level
- `option_economics.net_5m_pct` nested under `option_economics`
- `oi_vwap_checkpoint_timestamp` as the causal 5-minute OI/VWAP checkpoint

FIX1 incorrectly looked for top-level `net_5m_pct`.

FIX2 uses:
- quality_bucket for WINNER / LOSER grouping
- nested option_economics.net_5m_pct for the actual 5-minute option return
- oi_vwap_checkpoint_timestamp for OI alignment
- checkpoint - 5 minutes for true 5-minute OI change

Winner:
- EXCELLENT_5M_GE_10
- GOOD_5M_3_TO_10

Excluded:
- SMALL_WIN_5M_0_TO_3

Loser:
- LOSS_5M_0_TO_MINUS5
- LARGE_LOSS_5M_LE_MINUS5

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_oi_magnitude_feature_extractor_v1_fix2.py \
  tests/test_midpoint_oi_magnitude_feature_separation_v1.py -v
```

## Extract

```bash
python -m market_lab.midpoint_oi_magnitude_feature_extractor_v1_fix2 \
  --events-json data/historical-evidence/midpoint-global-session-exemplar-analysis-v1-development.json \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --output data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv
```

## Separate

```bash
python -m market_lab.midpoint_oi_magnitude_feature_separation_v1 \
  --features data/historical-evidence/midpoint-oi-magnitude-features-v1-development.csv \
  --output data/historical-evidence/midpoint-oi-magnitude-feature-separation-v1-development.json
```

If extraction still cannot align events to positioning snapshots, FIX2 fails loudly
instead of silently creating an empty study.
