# MIDPOINT V2 Break-and-Go Rebreak Exact Option Replay V1

This is the first and only predeclared option replay for the re-break hypothesis.

Structural diagnostic result:

- 20 frozen bearish immediate-confirmation candidates
- 8 genuine replayed INITIAL_SL5 exits
- 8/8 re-broke the original RED reference low
- 7/8 held below the boundary for the next close
- 1/8 was single-close only

This replay uses **only the 7 held-two-close cases**.

Entry rule:

1. original frozen trade exits under INITIAL_SL5;
2. first 1m CLOSE below original RED reference low;
3. next 1m CLOSE must also remain below the same low;
4. the second held close is the new confirmation timestamp;
5. select exact moving ATM PE at that confirmation timestamp;
6. enter at exact next-minute OPEN;
7. no nearest strike or time fallback.

Exit rule is unchanged:
`SL5_BE5_TRAIL3_AFTER10_TIME15`, including next-bar activation and 0.5pp costs.

No parameter sweep.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_rebreak_exact_option_replay_v1.py -v
```

Expected: 3 passed.

## Run

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

Interpretation discipline:

- Do not tune the hold count.
- Do not test single-close vs two-close based on P&L after seeing this.
- Do not widen SL5.
- Do not add an OI filter.
- Do not use E/F/G/H.
- Even a positive result is development evidence only; fresh OOS is still required.
