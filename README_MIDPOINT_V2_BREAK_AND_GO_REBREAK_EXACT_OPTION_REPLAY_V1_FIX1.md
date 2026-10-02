# FIX1 — Rebreak Exact Option Replay V1

The first replay failed before research execution because the positioning CSV
schema is wide, not one-option-per-row.

Observed schema includes:

- `moving_atm`
- `strike`
- `ce_instrument_key`
- `pe_instrument_key`

FIX1 supports this schema directly.

For bearish re-entry:
- use `pe_instrument_key`;
- exact ATM strike comes from the second-held-close underlying value;
- match that strike at the exact confirmation timestamp;
- no nearest strike fallback;
- no nearest timestamp fallback.

It still supports the older long schema if encountered.

Run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_rebreak_exact_option_replay_v1.py -v
```

Expected: 4 passed.

Then rerun the exact same replay command:

```bash
python -m market_lab.midpoint_v2_break_and_go_rebreak_exact_option_replay_v1 \
  --diagnostic data/historical-evidence/midpoint-v2-break-and-go-rebreak-reentry-diagnostics-v1-development.json \
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
  --output data/historical-evidence/midpoint-v2-break-and-go-rebreak-exact-option-replay-v1-development.json
```

Compact output:

```bash
jq '{
  research_version,
  source_schema_support,
  candidate_rule,
  exit_policy,
  summary,
  sep7_reference,
  rows,
  integrity,
  governance
}' \
data/historical-evidence/midpoint-v2-break-and-go-rebreak-exact-option-replay-v1-development.json
```
