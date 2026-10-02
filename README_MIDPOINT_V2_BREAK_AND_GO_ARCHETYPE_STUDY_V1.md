# MIDPOINT V2 Break-and-Go Archetype Study V1

Purpose: compare the 90-day population of frozen V1 bearish
`CONFIRM_CONTINUATION` events with 7 Sep 2026, without selecting days by option
P&L.

Candidate selection is fixed:

- date range: 2026-06-09 through 2026-09-07
- setup: RED_BREAK
- direction: BEARISH
- T+3 state: CONFIRM_CONTINUATION

Ranking uses only underlying follow-through after the exact next-minute entry:

- +5m close move
- +15m close move
- +30m close move
- +60m close move
- 60m maximum favorable excursion in Nifty points
- 60m maximum adverse excursion in Nifty points

OI quality and exact T+1 -> T+3 transition are carried descriptively.
Exact option economics and frozen exit result are joined descriptively if
available, but are never used to select/rank candidates.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_archetype_study_v1.py -v
```

Expected: 2 passed.

## Run

```bash
python -m market_lab.midpoint_v2_break_and_go_archetype_study_v1 \
  --state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --underlying data/historical-evidence/underlying-ohlc-train.csv \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --exit-research data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --start 2026-06-09 \
  --end 2026-09-07 \
  --output data/historical-evidence/midpoint-v2-break-and-go-archetype-study-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  window,
  selection_rule,
  summary,
  sep7_reference: {
    session_date,
    rank_by_underlying_mfe_60m,
    t1_observation_state,
    t1_oi_quality,
    t3_oi_quality,
    exact_oi_transition_t1_to_t3,
    price_pass_ratio,
    price_pass_count,
    primary_outcome,
    underlying,
    option_economics,
    frozen_exit
  },
  top10: [.ranked_rows[:10][] | {
    rank_by_underlying_mfe_60m,
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

## Interpretation

This phase is descriptive only.

Questions:

1. Where does 7 Sep rank by 60-minute underlying MFE?
2. Do the strongest trend days tend to keep STRONG OI through T+3, or can
   STRONG -> SECONDARY still produce large continuation?
3. On those large-follow-through days, did the frozen option exit capture the
   move or exit before the underlying continuation developed?
4. Is the key issue entry quality, option-path noise, or time/stop management?

Do not create a new OI filter or exit rule from this study alone.
