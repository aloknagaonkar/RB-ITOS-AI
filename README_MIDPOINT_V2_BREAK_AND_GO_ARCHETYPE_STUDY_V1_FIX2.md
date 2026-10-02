# FIX2 — Break-and-Go Archetype Study

FIX1 showed all 20 economics joins missing even though the Sep-7 exact economics
row is known to exist.

Root cause: the exact economics / exit research artifacts are not guaranteed to
expose their event records under a top-level `rows` array.

FIX2:
- discovers exact-economics records recursively;
- discovers frozen exit rows recursively;
- joins economics by session_date + setup_type + direction;
- joins frozen exit by session_date + direction + exact entry timestamp;
- resolves T+3 from:
  1. state t3_timestamp;
  2. economics t3_timestamp;
  3. exact entry timestamp minus one minute.

The third fallback is deterministic because the frozen entry contract is exact
next-minute OPEN after T+3. It is not inferred from future price or P&L.

Run tests:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_v2_break_and_go_archetype_study_v1.py -v
```

Expected: 6 passed.

Then rerun the exact same study command.

Quick validation after run:

```bash
jq '{
  research_version,
  source_discovery,
  summary,
  sep7_reference,
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
