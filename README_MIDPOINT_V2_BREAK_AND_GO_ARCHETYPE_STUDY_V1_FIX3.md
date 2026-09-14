# FIX3 — Break-and-Go Archetype Study

FIX2 correctly joined all 20 economics and frozen-exit rows, but only 8/20
underlying paths were available because the run supplied only:

`underlying-ohlc-train.csv`

The 20 frozen development candidates span TRAIN + OOS_A/B/C/D.

FIX3 adds repeated block-aware underlying arguments and block-aware joins.
Unavailable rows are no longer assigned fake ranks.

Run tests:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_archetype_study_v1.py -v
```

Then run:

```bash
python -m market_lab.midpoint_v2_break_and_go_archetype_study_v1 \
  --state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --exit-research data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --start 2026-06-09 \
  --end 2026-09-07 \
  --output data/historical-evidence/midpoint-v2-break-and-go-archetype-study-v1-development.json
```

Compact check:

```bash
jq '{
  research_version,
  source_discovery,
  summary,
  sep7_reference,
  top10: [.ranked_rows[:10][] | {
    rank_by_underlying_mfe_60m,
    block,
    session_date,
    t1_oi_quality,
    t3_oi_quality,
    exact_oi_transition_t1_to_t3,
    price_pass_count,
    underlying,
    option_economics,
    frozen_exit
  }],
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-break-and-go-archetype-study-v1-development.json
```
