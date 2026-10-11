# V2 replay on frozen 18 bullish + 18 bearish dates

Uses exact cohort from scripts/hilega_60_session_directional_validation.py and Midpoint V56.5; preserved in cohort.json. Session labels are retrospective diagnostics only and are attached AFTER replay. No future direction is passed to strategy. Does not install, publish UI, invoke broker APIs, change services or enable live/Sandbox orders.

Extract folder into RB-ITOS-AI. No other new package is required; engine/warmup are included. Uses installed market_lab.hilega_v2_alignment_replay_v1 and existing local Nifty caches.

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_v2_confirmed36_validation/run.py --self-test &&
PYTHONPATH=backend:. .venv/bin/python hilega_v2_confirmed36_validation/run.py
```

Output: data/historical-evidence/hilega-v2-confirmed36-validation-v1. Fresh output required; --output-root supplies a different path. Optional repeatable --cache-root replaces defaults (supply every desired warmup/recovery root). Later roots take priority.

Four full-lifecycle policies:
- BASELINE: current V2 alignment + minute strength/persistence + dual exit.
- ALL_SLOPES_5M: completed5m entry/exit, all three entry slopes directionally aligned, all three opposite slopes for dual exit.
- ALL_SLOPES_5M_EMA10_ENTRY: above plus bullish price close above5m priceEMA10 / bearish below.
- ALL_SLOPES_5M_EMA10_ENTRY_EXIT: above plus opposite priceEMA10 side mandatory for exit, AND every dual/slope condition.

Entries retain strict5m canonical-or-alternative setup, RSI/EMA/WMA ordering, positive expanding directional gap. No numeric strength floor, PCR or Midpoint filter is added. Alternative episode rejection/retry behavior remains as preceding test. All entry and exit conditions must pass on same completed candle, no warning latch for EMA10. Cutoff14:55 exact open overrides all filters. Exit before same-boundary new entry; one position. EMA10 on Nifty closes uses alpha2/11 seeded at first warmup close and carried across sessions. First slope comparison uses prior-session last completed indicator, explicitly labeled. Shared warmup cached incrementally and deep-copied, preserving causal state; keep input files unchanged during run.

Output files:
- summary.csv: by bullish/bearish session label, aligned/counter-trend/all, policy.
- daily.csv: exact date-wise results, including evaluated zero-trade days.
- trades.csv / losses.csv: detailed trades and stored entry/exit checks.
- entry_details.csv: flattened previous/current indicators, slopes, gap/delta, strength, EMA10. For BASELINE these are provisional-minute entry values; separate completed5m_at_entry and completed5m_changes_at_entry columns show latest completed candle from its audit (first-session slope may be unavailable).
- attribution.csv: matched/new/removed entries versus current V2.
- coverage.csv: each of36 dates, missing/empty/failed/evaluated.
- sessions/<date>/<policy>.json: full decision audits.
- report.json: exact cohort, hashes, coverage, summaries, complete_36 flag.

If any target date is missing/empty/fails, process returns exit code2 AFTER saving partial results. A partial report is not a complete36 result. Do not replace missing days with zero-trade days or synthesize candles. All policies contribute only where all four evaluated successfully. Warmup needs earlier full-session caches; no broker acquisition is attempted. Local partial smoke test used only dates available in uploaded recovery inputs, not full cohort.

Nifty points exclude costs/options fills; reconstructed indicator parity with live/charts unverified. This frozen trend-day cohort was historically selected and is not independent out-of-sample. Alignment grouping does not prove a causal entry filter would avoid every counter-trend loss. No arming/deployment commands needed.
