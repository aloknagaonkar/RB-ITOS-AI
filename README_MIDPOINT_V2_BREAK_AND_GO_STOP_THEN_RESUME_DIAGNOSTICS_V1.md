# MIDPOINT V2 Break-and-Go Stop-Then-Resume Diagnostics V1

The prior Early Path Diagnostics produced:

- 12 IMMEDIATE_FOLLOW_THROUGH
- 4 DELAYED_FOLLOW_THROUGH
- 4 FAILED_CONTINUATION

The delayed and failed groups did **not** show a clean one-bar or three-bar
post-entry separator. Examples overlap:

- delayed cases include negative and positive +1m paths;
- failed cases also include negative and positive +1m paths.

Therefore this phase does **not** replay a delayed-entry rule.

Instead it asks a safer structural question:

> After the frozen V1 stop has already occurred, how often does the underlying
> subsequently resume the original bearish direction?

This preserves the original V1 entry and exit completely.

Resume classification is descriptive and sign-only relative to the underlying
close on the frozen exit bar:

- RESUMED_BY_15M
- RESUMED_BY_30M
- RESUMED_BY_60M
- NO_RESUME_BY_60M

No option re-entry is simulated. No SL threshold is changed.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_stop_then_resume_diagnostics_v1.py -v
```

Expected: 4 passed.

## Run

```bash
python -m market_lab.midpoint_v2_break_and_go_stop_then_resume_diagnostics_v1 \
  --state data/historical-evidence/midpoint-stable-feature-state-machine-v3-2-development.json \
  --exit-research data/historical-evidence/midpoint-v3-2-exit-management-research-v1-development.json \
  --underlying 'TRAIN|data/historical-evidence/underlying-ohlc-train.csv' \
  --underlying 'OOS_A|data/historical-evidence/underlying-ohlc-oos-a.csv' \
  --underlying 'OOS_B|data/historical-evidence/underlying-ohlc-oos-b.csv' \
  --underlying 'OOS_C|data/historical-evidence/underlying-ohlc-oos-c.csv' \
  --underlying 'OOS_D|data/historical-evidence/underlying-ohlc-oos-d.csv' \
  --output data/historical-evidence/midpoint-v2-break-and-go-stop-then-resume-diagnostics-v1-development.json
```

Compact output:

```bash
jq '{
  research_version,
  candidate_scope,
  resume_taxonomy,
  summary,
  sep7_reference,
  rows: [.rows[] | {
    block,
    session_date,
    t1_oi_quality,
    t3_oi_quality,
    exact_oi_transition_t1_to_t3,
    price_pass_count,
    exit_timestamp,
    exit_reason,
    frozen_net_return_pct,
    post_exit_underlying
  }],
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-break-and-go-stop-then-resume-diagnostics-v1-development.json
```

## Decision rule

If stop-then-resume is common, the next research question should be a **fresh
structural re-entry mechanism**, not a wider initial stop and not a blanket
delayed first entry.

If stop-then-resume is rare, keep V1 stop behavior and do not pursue re-entry.

No rule promotion from this diagnostic alone.
