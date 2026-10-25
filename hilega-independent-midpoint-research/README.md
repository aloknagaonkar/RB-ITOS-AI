# Independent body route + post-entry midpoint protection

Research only. Extract as a NEW folder into ~/RB-ITOS-AI. No live files/settings/services/orders changed. Tests and replays have not been run locally; run on VM. Source syntax parsed only.

Only independent-route positions receive protection. Bullish: exit on a completed1m CLOSE below original signal(high+low)/2. Bearish: exit on a completed1m CLOSE above it. Equality holds. Wick touch does not exit. Start with the first1m close AFTER entry. Midpoint is fixed, not trailing and not body midpoint. Exit uses the observed close, not an assumed fill at midpoint. Fees/slippage/options not modeled.

Existing5m exits/reversal remain enabled; whichever fires first closes once.14:55cutoff overrides midpoint and uses existing cutoff pricing. At other5m boundaries midpoint is checked before5m policy evaluation; after a midpoint exit fresh independently qualifying setups or existing entries may be evaluated on that boundary. No immediate re-entry using the consumed old signal. Clear pending reference and support observer on protection exit. Historical strategy state changes can affect later trades.

Entries unchanged: existing route retained while flat. Extra independent route requires completed5m green/red body>60% of range; strict actual body straddle of priceEMA10 and directionalEMA10 slope. No outer25%close,50%beyond,existing-setup,RSI/WMA/gap filters.1m close breakout of signalhigh/low confirms; reverse midpoint cancels waiting. One position. Same-direction later existing confirmation remains audit-only, never adds quantity or resets entry.

## VM: test7August first

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-independent-midpoint-research/test_independent.py \
  hilega-independent-midpoint-research/test_midpoint.py

PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-independent-midpoint-research/batch.py \
  --input-zip data/research/hilega-one-minute-input-20261022/timing-input.zip \
  --session-input data/research/hilega-one-minute-input-20261022/session-input.json \
  --date 2026-08-07 \
  --output data/research/hilega-independent-midpoint-20260807

.venv/bin/python hilega-independent-midpoint-research/compare.py \
  --old-root data/research/hilega-independent-body-20260807 \
  --new-root data/research/hilega-independent-midpoint-20260807

cat data/research/hilega-independent-midpoint-20260807/three-policy-summary.md
cat data/research/hilega-independent-midpoint-20260807/three-policy-signals.md
```

The3columns compare deployed5m, unprotected independent combined, protected independent combined. Raw protected policy key INDEPENDENT_BODY_1M_MIDPOINT_EXIT. `three-policy-signals.md` has direction/setup/entry–exit/points; `new-signal-values.md` has price/indicators/body values. DailyJSON stores all ACTIVE_MIDPOINT_EXIT_CHECK and MIDPOINT_EXIT records. `daily-reports/date.md` includes each1m protection check with fixedmidpoint, close, direction and pass/fail. Reports use grossNIFTY candle marks, not broker fills. Old/new input archives must match. Comparison excludes incomplete days and unequal baseline trade signatures.

For a wider run, use tmux and replace the date option with `--month 2026-08 --month 2026-09 --month 2026-10`, using a separate output directory. First generate unprotected independent results for the same dates with the original independent-body package; use that directory for --old-root. Daily caches are keyed by source/input hashes. No profit improvement is assumed until replay completes.
