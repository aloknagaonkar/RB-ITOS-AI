# MIDPOINT V2 Break-and-Go Rebreak Re-entry Diagnostics V1

Purpose: validate a structural re-entry hypothesis **without replaying option P&L**.

The prior stop-then-resume study showed that post-stop bearish continuation was
common, but that study mixed initial SL5, breakeven, trailing, and profitable
stop exits.

This phase fixes that by requiring **explicit stop attribution**.

Only rows explicitly attributed to `INITIAL_SL5` are eligible. The module does
not infer `INITIAL_SL5` from a -5.5% net result.

For each eligible event:

1. keep the frozen original RED reference low;
2. keep the frozen original exit unchanged;
3. after the exit, watch up to 60 minutes;
4. find the first 1m CLOSE below the original RED reference low;
5. record whether the next 1m CLOSE also stays below the boundary;
6. measure underlying follow-through after that re-break.

No option re-entry is simulated yet.

## Locate the stop-attribution artifact

If unsure of the filename:

```bash
find data/historical-evidence -maxdepth 1 -type f | \
  grep -Ei 'e15.*stop.*regime|stop.*regime.*attribution'
```

The expected artifact is the development JSON produced by
`MIDPOINT_V2_E15_STOP_REGIME_ATTRIBUTION_V1`.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_rebreak_reentry_diagnostics_v1.py -v
```

Expected: 4 passed.

## Run

Replace `<STOP_ATTRIBUTION_JSON>` with the file returned by the `find` command:

```bash
python -m market_lab.midpoint_v2_break_and_go_rebreak_reentry_diagnostics_v1 \
  --state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --exit-research data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --stop-attribution <STOP_ATTRIBUTION_JSON> \
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
    stop_regime,
    frozen_exit,
    rebreak
  }],
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-break-and-go-rebreak-reentry-diagnostics-v1-development.json
```

## Decision rule

Do not replay options yet.

A one-shot exact-option re-entry replay is justified only if:

- explicit `INITIAL_SL5` attribution is available for the candidate set; and
- original-boundary re-break appears consistently in genuine resume cases; and
- genuine failures often do not produce the same held re-break signature.

If that split is weak, reject this re-entry hypothesis.

Do not use E/F/G/H.
