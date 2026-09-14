# FIX1 — Break-and-Go Rebreak Re-entry Diagnostics

The first run returned zero stop attribution and null reference boundaries.

That was a source mismatch, not a research finding.

## Root causes

1. `midpoint-v2-e15-stop-regime-attribution-v1-development.json` is for the
   **17 V2 new-arm candidates** (BASE_THEN_GO + FAILED_BREAK_RECLAIM). It is not
   an attribution artifact for the frozen V1 immediate-confirmation population.

2. `midpoint-stable-feature-state-machine-v3-2-development.json` does not carry
   `reference_low` / `reference_high` on these event rows.

FIX1 therefore:

- does not consume the V2 new-arm stop-attribution artifact;
- explicitly attributes V1 stop regime by replaying exact option OHLC only up
  to the already-frozen V1 exit timestamp;
- never re-selects the exit timestamp;
- uses only bars strictly before the frozen exit bar for BE/trailing
  activation, preserving next-bar activation semantics;
- loads the original RED boundary from
  `opening-candle-midpoint-framework-v1-1-development.json`;
- then performs the same underlying-only close re-break diagnostic.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_rebreak_reentry_diagnostics_v1.py -v
```

Expected: 2 passed.

## Run

```bash
python -m market_lab.midpoint_v2_break_and_go_rebreak_reentry_diagnostics_v1 \
  --state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --framework data/historical-evidence/opening-candle-midpoint-framework-v1-1-development.json \
  --economics data/historical-evidence/midpoint-v3-2-exact-option-economics-v1-development.json \
  --exit-research data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --option-ohlc 'TRAIN|data/historical-evidence/option-ohlc-train.csv' \
  --option-ohlc 'OOS_A|data/historical-evidence/option-ohlc-oos-a.csv' \
  --option-ohlc 'OOS_B|data/historical-evidence/option-ohlc-oos-b.csv' \
  --option-ohlc 'OOS_C|data/historical-evidence/option-ohlc-oos-c.csv' \
  --option-ohlc 'OOS_D|data/historical-evidence/option-ohlc-oos-d.csv' \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-break-and-go-rebreak-reentry-diagnostics-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  source_correction,
  candidate_scope,
  rebreak_definition,
  summary,
  sep7_reference,
  eligible_rows: [.rows[] | select(.eligible_initial_sl5 == true) | {
    block,
    session_date,
    reference_low,
    t1_oi_quality,
    t3_oi_quality,
    exact_oi_transition_t1_to_t3,
    price_pass_count,
    primary_outcome,
    stop_attribution,
    frozen_exit,
    rebreak
  }],
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-break-and-go-rebreak-reentry-diagnostics-v1-development.json
```

Do not use E/F/G/H. Do not replay option re-entry until this structural split is
known.
