# MIDPOINT V2 E15 Stop-Regime Attribution V1

The raw stop-path diagnostic showed many contracts cross the -5% level and later
recover. That alone does NOT prove the frozen initial SL5 caused the actual exit,
because the E15 engine may already have moved its stop to breakeven or trailing.

This module joins:

- `MIDPOINT_V2_EXIT_DURATION_COMPARISON_V1`
- `MIDPOINT_V2_STOP_PATH_DIAGNOSTICS_V1`

and classifies every E15 stop exit using the actual stop state active at exit:

- `INITIAL_SL5`
- `BREAKEVEN`
- `TRAILING`
- `NOT_STOP_EXIT`

Only genuine `INITIAL_SL5` exits are used for the recovery diagnostic.

## Linux test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_e15_stop_regime_attribution_v1.py -v
```

Expected: 4 tests.

## Run

```bash
python -m market_lab.midpoint_v2_e15_stop_regime_attribution_v1 \
  --exit-comparison data/historical-evidence/midpoint-v2-exit-duration-comparison-v1-development.json \
  --stop-path data/historical-evidence/midpoint-v2-stop-path-diagnostics-v1-development.json \
  --output data/historical-evidence/midpoint-v2-e15-stop-regime-attribution-v1-development.json
```

## Compact output

```bash
jq '{
  research_version,
  candidate_count,
  overall_summary,
  arm_summaries,
  direction_summaries,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-e15-stop-regime-attribution-v1-development.json
```

## Decision discipline

Do NOT widen the stop yet.

If `FAILED_BREAK_RECLAIM` still shows repeated recovery after genuine
`INITIAL_SL5` exits, then define one predeclared reclaim-only stop hypothesis.

If most apparent recoveries were actually BE/trailing exits, then the initial
SL5 is not the main problem and stop widening would target the wrong mechanism.
