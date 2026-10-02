# FIX2 — Rebreak Exact Option Replay V1

FIX1 reached the 7 structural candidates but all returned
`AMBIGUOUS_EXACT_ATM_PE`.

The inspection showed why:

At each timestamp the positioning file has 11 rows covering offsets -5..+5.
All rows share the same `moving_atm`, while `strike` is the actual strike and
`strike_offset == 0` identifies the ATM row.

FIX1 incorrectly copied `moving_atm` into every row's strike field, making all
11 rows look like ATM.

FIX2 corrects the schema:

- `moving_atm` = snapshot ATM reference
- `strike` = actual option strike
- `strike_offset == 0` = canonical ATM row
- `pe_instrument_key` = exact PE instrument
- exact timestamp required
- no nearest strike fallback
- no nearest time fallback

The inspection also showed one expiry per snapshot, so there is no expiry
ambiguity in these seven cases.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_rebreak_exact_option_replay_v1.py -v
```

Expected: 4 passed.

## Replay

Run the same command:

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
