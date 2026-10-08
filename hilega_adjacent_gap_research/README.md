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

V2 adds `gap_status` and `decision_reasons` to each minute check, plus a
`gap_categories` summary grouped by the first actionable observation per signal.
Categories: positive widening, unchanged, narrowing, crossed positive, negative
improving/not improving, zero, and data unavailable. These are diagnostic labels,
not newly optimized width thresholds or profitability guarantees. Category
outcomes include later entries within the existing window; they do not mean
entry occurred immediately at the first categorized observation.
The full VM run is currently blocked by frozen indicator parity divergence
first seen September 25 after the last matching September 23 observation.
This update deliberately retains that guard; no valid 490-session result is claimed.

## Reconcile the observed September divergence

The optional read-only reconciliation runner tests whether September 24 was
absent from the original warmup cohort. It creates temporary symlinks, never
removes a cache, refuses to exclude a date containing frozen trades, and compares
all frozen trace prices, RSI, EMA and WMA states. It runs the first-touch research
only after complete observation parity, recording input hashes and the omitted
date in `history-reconciliation.json`. If it fails, no comparison is published.

```bash
PYTHONPATH=backend:. python hilega_adjacent_gap_research/reconcile_frozen_history.py --run-if-parity-matches
```

This is historical cohort reproduction, not a recommendation to ignore
September 24 in live trading. Any future current-data comparison needs a
separately regenerated canonical signal/control cohort.

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

## Loss attribution after the reconciled run

Run `python hilega_adjacent_gap_research/analyze_gap_losses.py --self-test`, then
`python hilega_adjacent_gap_research/analyze_gap_losses.py` from the repository root.
This reads the already generated reconciled report without rebuilding indicators.
Output: `data/historical-evidence/hilega-adjacent-gap-loss-diagnostics-v1/report.json`.

Groups separate BOTH_ENTERED (entry timing), EARLIER_RULE_ONLY (additional
setups), WAITING_RULE_ONLY (lost opportunities), and BOTH_DENIED. Each group
shows bullish/bearish gains, losses, net and gain/loss ratio. Gap width and
expansion bands describe the candidate entry, with development-block breakdowns.
The trades section retains entry checks, previous/current indicators, both
entry times/prices, common exit and results, sorted by worst policy difference.
Bands are descriptive; they are not validated thresholds or live changes.

## Entry condition diagnostics

Run `python hilega_adjacent_gap_research/analyze_entry_conditions.py --self-test`
then `python hilega_adjacent_gap_research/analyze_entry_conditions.py`.
Reads the reconciled report; writes a separate entry-condition-diagnostics report.
Displays fixed gap, expansion and WMA strength bands and RSI/EMA/WMA alignment
and EMA continuation, separately for bullish/bearish, shared/additional trades,
and the three development blocks. These are entry-time descriptive groups, not
a backtested new policy or independent validation. Keep the live rule unchanged.
