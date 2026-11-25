# Bullish optimization v1 — research candidates

This is a NEW standalone research directory. It does not modify backend/frontend files, settings, services or orders. User runs pytest/replays on the VM. Local preparation is source AST syntax validation and saved-result arithmetic only, not a strategy replay or local test run.

## Baseline

Last uploaded research control: bearish body-cross OR already-below continuation, strict bullish body-cross, independent midpoint protection ON, existing 5m route/exits retained. Not a claim about the current live installation. October26 1m control: full-day +69.15 gross points; bullish 8 trades / 2 winners / 6 losers / +95.25; bearish −26.10. Current bullish qualification is green body >60%, open < EMA10 < close and rising EMA10; later completed 1m close above original high confirms. Pending cancels on a later close below original range midpoint. Post-entry independent midpoint exit is strictly below it; equality holds.

## Six candidates (per selected signal interval)

Entry A CROSS_ONLY: existing strict bullish body cross.
Entry B CROSS_OR_ABOVE: strict cross OR EMA10 < open < close, still green, body/range >0.60, rising EMA10. No new RSI/WMA/gap/strength filter.

Each combines with:
- MIDPOINT_ONLY: current protected exits, control.
- TRAIL20_10: after a prior completed 1m close reaches at least +20 points, exit if a later completed close is at least 10 points below the running completed-close peak.
- TRAIL40_20: activation +40 points, giveback 20 points.

These two fixed threshold pairs are pre-existing research candidates, not optimized values or guarantees of positive exit P&L. No threshold grid search or best rule claim. The purpose is to test entry and exit changes separately and together.

Profit exits apply only to independent bullish positions. Midpoint remains enabled for independent trades, including bearish positions. Bearish qualification and exit logic are unchanged, but altered bullish occupancy can change subsequent bearish opportunities and full-day P&L. Original 5m entry route, dual RSI/WMA exits/reversal remain enabled; existing-route positions do not receive the new independent-only protection. One position, no averaging; later existing support stays informational. First eligible new signal can be evaluated after a closed trade; the consumed old signal is not reused.

All checks use available completed bars. Profit exit reads only the peak from previous completed closes; current close updates peak after the decision. Peak never uses intrabar extremes. Exit executes at observed current close, not at the trail threshold; adverse jumps may overshoot into a loss. Giveback equality triggers the new profit exit. Midpoint equality still holds. On a shared close both conditions can be true; midpoint has exit-reason priority. Checks run before normal 5m evaluation except the 14:55 cutoff, which overrides at exact minute OPEN. Original signal midpoint remains fixed, not trailed.

## VM: tests then first 1m experiment

Download ZIP to ~/RB-ITOS-AI. Extract new folder:

```bash
cd ~/RB-ITOS-AI
unzip hilega-bullish-optimization-v1-20261104.zip

PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-bullish-optimization-v1/test_bullish.py
```

Only after tests pass:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-bullish-optimization-v1/run.py \
  --input-zip data/research/hilega-timeframe-input-20261026/timing-input.zip \
  --session-input data/research/hilega-timeframe-input-20261026/session-input.json \
  --signal-interval 1 \
  --output data/research/hilega-bullish-optimization-20261026-v1
```

One existing 5m control + six 1m candidate combinations, including the protected baseline. Default is 1m. To compare all signal intervals, repeat `--signal-interval 1 --signal-interval 3 --signal-interval 5` in a separate run with a NEW output directory. Existing route/exits remain 5m; confirmation/protection are always 1m. EMA10 uses ten bars of the selected signal timeframe. Intervals anchored 09:15; only complete bars, no partial 3m candle at 14:55.

Source hashes must match the recorded research baseline; mismatch blocks and should be reviewed, not bypassed. Saved input hashes must match October26 uploaded results. Same warmup cache roots are searched; additional root can be provided by --cache-root. Existing output directory blocks; use fresh output.

First reproduce actual recorded 5m bars; failure blocks. API-versus-recorded-live parity is retained independently (known FAIL on the supplied later API data). Both the original extended engine and the new default engine must match uploaded protected trade signatures for each requested timeframe. Original 5m control must match too. Source/data changes must be resolved, not waived.

## Outputs / interpretation

Upload `data/research/hilega-bullish-optimization-20261026-v1/results.zip`.

report.html and report.json: every policy, complete trade list, bullish/bearish/full-day P&L, closed drawdown, exit reasons, peak profit/time and giveback, full audit including profit checks, source/input metadata and regressions. comparison.md includes result without the largest winner. failure.json is written if blocked; no results ZIP is produced until required controls pass.

Peak profit uses completed 1m closes strictly after entry through actual exit, floored at zero. It is descriptive hindsight, not assumed achievable profit. Closed-trade drawdown excludes intratrade excursions. Gross NIFTY index marks exclude options, fees, slippage and latency. October26 has already been examined extensively; its result cannot select a production optimum. Test frozen rules on additional unseen sessions before choosing. No unseen-session result is claimed in this package.

Open `bullish-baseline-review.html` for the completed saved-data audit; no candidate replay numbers are presented there.
