# Actual preceding-minute gap research

This is a standalone read-only test, not an installer. Keep this folder inside
RB-ITOS-AI. No restart or strategy/order changes are needed.

```bash
source .venv/bin/activate
PYTHONPATH=backend:. python hilega_adjacent_gap_research/research_adjacent_gap.py --self-test
PYTHONPATH=backend:. python hilega_adjacent_gap_research/research_adjacent_gap.py
```

Default input: frozen `hilega-wma-gap-490-v1/trade-results.csv` and
`candidate-timeline.csv`, plus `hilega-milega-underlying-cache-v1` exact caches.
Default output: `data/historical-evidence/hilega-actual-adjacent-gap-490-v1/report.json`.
If output already exists, use a fresh `--output-root`; earlier output is preserved.

Policy: canonical signal -> current WMA strength >=0.75 -> current directional
gap positive and strictly greater than actual preceding minute gap. Enter at
that minute's close, using the existing recorded confirmation window; retain
the canonical exit convention. EMA continuation and RSI alignment are not gates.
The preceding minute is reconstructed with its own close and the state before
its five-minute slot; this includes the minute before the first existing trace.
It is not a five-minute reference substituted for an adjacent minute.

All rebuilt current values must match frozen control indicator values. Missing
previous observation means WAIT, not contraction. Parity mismatch stops the run.
The script checks for 490 trade-bearing dates; if this differs from your frozen
session registry, investigate zero-signal dates rather than relabelling a partial run.

Report includes control vs candidate summaries, chronological development blocks,
bullish/bearish separation, every trade's signal/entry/exit, points, previous and
current EMA/WMA/gap at entry, minute checks, and denied winner/loss/MFE setup counts.
Denied +20/top-decile counts are denied original MFE setups, not measures of
post-entry excursion retention. No fees, slippage, option P&L or broker fills.
All inspected historical sessions are development evidence. No untouched cohort
is claimed and no strategy is enabled by this test.

Local validation used supplied reconstructed October 6–7 evidence (23 trades):

| Direction | Waiting rule net | Actual preceding-minute rule net |
|---|---:|---:|
| Bullish | -7.85 | +9.50 |
| Bearish | -66.80 | -54.80 |
| All | -74.65 | -45.30 |

Earlier preliminary analysis omitted six initial comparisons; these results now
include their reconstructed preceding minute. They do not constitute a 490-session
result. Full 490-session files are on your VM and must be tested there.
