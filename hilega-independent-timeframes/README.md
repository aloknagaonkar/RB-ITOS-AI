# Independent body-cross + midpoint: 26 October / 1m, 3m, 5m

Research package only. Does not modify installed strategy files, restart services, or place orders. Run tests and replay on the VM. Sources were syntax-checked here only; no tests or strategy replays were run locally.

## Comparison scope

Seven full-state policies on the SAME later API minute input: existing 5m control, and independent signal candles of 1m/3m/5m, each with post-entry midpoint protection OFF/ON. The existing 5m entry route and its RSI/WMA exits/reversal stay enabled and unchanged in EVERY policy. This is signal-cadence research; it does not move the existing strategy or exits to 1m/3m.

Signal: completed directional candle, absolute body / range > 0.60, strict open/close straddle of its price EMA10, EMA10 slope in direction. No setup/RSI/WMA/gap/strength filters for the extra route. EMA10 is 10 candles of the selected signal interval, seeded using all supplied prior sessions; it is not a common elapsed-time EMA. Intervals anchor at 09:15 IST. 3m has no partial 14:55 candle (last complete bar ends 14:54).

A later completed 1m close above original signal high / below original signal low enters. Before entry, a completed 1m close through the opposite original signal midpoint cancels waiting. Equality holds. Preserve earliest same-direction reference; a new eligible opposite signal replaces waiting; a qualified opposite existing-watch event may cancel it. No fixed wait expiry; cutoff ends waiting.

Protection ON: only independent-route trades exit on a later completed 1m close below original signal midpoint (bullish), above it (bearish). Equality holds. No wick/touch exit. Fixed range midpoint, not body midpoint or confirmation midpoint. Exit price is observed 1m close. No check on entry's own close. Existing-route positions are not protected by this new rule. Existing exits still apply. One position, no quantity addition; later existing support is audit-only. Existing entry has priority on shared 5m boundaries. Midpoint checks precede the 5m policy except cutoff; consumed signals cannot re-enter. New fully qualified signals can arm after an exit.

14:55 IST cutoff has priority and uses the exact minute OPEN. All minute/decision times are IST. Gross NIFTY index candle marks only; no option or futures fills, slippage, fees or latency. Closed-trade drawdown excludes intratrade excursions. ON/OFF full-state runs can change later setups/entries, not just exit values.

## VM commands

Download ZIP to ~/RB-ITOS-AI, extract its NEW folder (no production paths in ZIP):

```bash
cd ~/RB-ITOS-AI
unzip hilega-independent-timeframes-20261026.zip

PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-independent-timeframes/test_independent.py \
  hilega-independent-timeframes/test_midpoint.py \
  hilega-independent-timeframes/test_timeframes.py
```

Only after tests pass:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-independent-timeframes/run.py \
  --input-zip data/research/hilega-timeframe-input-20261026/timing-input.zip \
  --session-input data/research/hilega-timeframe-input-20261026/session-input.json \
  --output data/research/hilega-independent-timeframes-20261026
```

If the output directory exists, use a new `--output` directory; do not overwrite it. A pre-existing package folder is not overwritten by default unzip: use a separate clean extraction if needed.

Source hashes must match the earlier validated input package. A mismatch blocks execution; do not bypass it. Missing Oct22/23 warmup also blocks execution; the same three VM cache roots from the previous run are searched. An additional root can be supplied with `--cache-root`.

## Parity and controls

First reproduce actual recorded 5m bars/indicators/trades; failure blocks. Then separately retain API-versus-live parity (previously FAIL on this date); COMMON_LATER_API is explicitly labelled and does not recover original live minutes. Exact trade-signature regression against the original protected AND unprotected 5m research engines must pass before a comparison is produced. No change to the original strict live-parity mode.

Outputs: `report.json` (all trades/audits/values), `report.html` (seven-policy overview and full trade/audit details), `comparison.md`, `manifest.json`, both parity checks, original-5m regression check, `results.zip`.

Upload `data/research/hilega-independent-timeframes-20261026/results.zip` for analysis. A blocked run writes `failure.json`; provide that and parity/regression outputs if no results ZIP is produced. No result is claimed by preparing this package.
