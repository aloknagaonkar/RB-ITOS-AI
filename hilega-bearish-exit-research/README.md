# Bearish exit WMA40 study — 8, 12, 19 October

Research only, no installer/service restart/live strategy writes. Run from the
RB-ITOS-AI root on the Ubuntu VM. Tests and replay have not run locally.

Variants:

1. CURRENT: installed BULLISH_GAP2_FULL_WMA2, completed 5m signal/followup/exits.
2. WMA40_EXIT_ONLY: bearish normal dual exit additionally requires current
   WMA21 of RSI9 >40. Equality holds. Both conditions must pass together; no latch.
3. WMA40_EXIT_PLUS_CONFIRMED_REVERSAL: same exit restriction, plus fully confirmed
   bullish entry may close bearish and enter bullish at the same boundary.

All normal bullish checks are retained: alignment, signal strength>=0.75,
positive expanding gap with bullish signal gap>=2, price EMA10 side/slope,
green candle, rising RSI>40, later completed followup with green/rising RSI,
price route OR fresh strength/gap route, bullish full WMA magnitude>=2.
The opposite monitoring context is independent and starts after bearish entry.
It evaluates bullish candidates while the real bearish position remains open.
It never opens a second position. No bullish setups before bearish entry are
carried into it. Arms/qualification alone cannot reverse. After exit/reversal
that monitor is discarded. New bearish entries start a new monitor.

Bullish normal exits and 14:55 cutoff remain unchanged. All entries/exits use
the existing completed-boundary close convention; cutoff uses exact14:55 open.
Delayed exits and reversals alter subsequent setup availability and trade paths.

```bash
PYTHONPATH=backend:. .venv/bin/python hilega-bearish-exit-research/test_exit.py
PYTHONPATH=backend:. .venv/bin/python hilega-bearish-exit-research/run.py \
  --input-zip /tmp/hilega-timing-input-2026-10-21.zip \
  --date 2026-10-08 --date 2026-10-12 --date 2026-10-19 \
  --output data/research/hilega-bearish-wma40-exit-oct8-12-19
```

Baseline trades must match the installed historical replay on identical inputs.
This is historical reconstruction, not evidence of historical live fills.
Source hashes must match the previously uploaded implementation. At least20
prior nonempty full-session warmup caches are required. Incomplete days are
reported and excluded. Use comparison.md and report.json; per-day JSON includes
every bearish exit check, opposite monitor checks, entries and exit reasons.
Gross NIFTY points exclude option fills, costs and slippage.
