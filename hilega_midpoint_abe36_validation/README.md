# Exact 36-session V2 + Midpoint A/B/E validation

Run from RB-ITOS-AI with its venv. No installer or service restart.

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_midpoint_abe36_validation/run.py --self-test
PYTHONPATH=backend:. .venv/bin/python hilega_midpoint_abe36_validation/run.py
```

Baseline is your installed alignment/dual-exit V2 engine, unchanged. A/B/E are enabled inside offline Midpoint configuration only; other environment configuration is captured in report.json. Only accepted SHADOW_ENTRY A/B/E events establish direction. Setup and every pending entry must match. Candle timestamp becomes available one minute later. Opposite confirmations flip direction; simultaneous opposing confirmations neutralize it. Close crossing against the confirmed reference midpoint neutralizes trend until a new accepted confirmation. Equality retains direction. No active-trade forced exit is added.

cohort.json contains the exact 18 bullish + 18 bearish dates. Labels only group results after replay and never drive trend. Warmup uses only earlier caches, incrementally retained and copied before replay. Inputs are never modified. Missing inputs fail coverage, never count as zero trades. Exit code 2 means incomplete coverage; do not treat that as a full 36-session result.

Default Midpoint source: data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1/YYYY-MM-DD/minutes.jsonl, then October recovery roots. Use --midpoint-root /path/to/date-folders for another source. Each minute needs timestamp, underlying OHLC, futures_close, futures_vwap, futures_volume. Exact matching Nifty data and the 09:15–14:54 strategy window are required. No broker download is performed.

Output: data/historical-evidence/hilega-midpoint-abe36-v1. daily.csv compares every covered date; trades.csv includes entry/exit/points and confirming family; filter-checks.csv explains blocked setup/entry checks; sessions/ holds full baseline/filtered replay, trend timeline and Midpoint audit; summary.csv groups session labels/alignment; family-summary.csv groups accepted entries by A/B/E; coverage.csv lists missing data. report.json records configuration/hashes and complete_36_sessions. Re-runs require a fresh --output-root. Results are reconstructed Nifty points before costs, not option P&L.
