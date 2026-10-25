# Strict body crossing research

Separate research directory. No live code, services, orders or strategy configuration modified. Tests and replay must run on your VM; not run locally. Python source was syntax-parsed only.

| Check | Previous BODY50 | New BODY60 cross |
|---|---|---|
| Body / full high-low range | >=60% | >60% |
| Open/close straddle completed price EMA10 | Required | Required |
| Body fraction beyond EMA10 | >50% | No minimum |
| Wick-only or body endpoint equality | Reject | Reject |
| Directional candle colour / EMA10 slope | Required | Unchanged |
| Close in directional outer25% | Required | Unchanged |
| Recorded setup required | Yes | Unchanged |
| Completed1m close breaks signal high/low | Yes | Unchanged |
| Cancel waiting on1m close reversing fixed high-low midpoint | Yes | Unchanged |
| Existing route and deployed exits | Retained | Unchanged |

This comparison uses the unprotected BODY50_1M_WAIT control. Post-entry midpoint exit is NOT included. It is a separate experiment, not the waiting-stage midpoint cancellation. New breakout trades are marked BODY60_CROSS_1M_BREAKOUT. For compatibility the underlying result JSON still calls the tested policy BODY50_1M_WAIT; interpret that key as the NEW variant only within this output directory. The three-policy reports use explicit old/new labels.

On 7Aug10:00–10:05 the body ratio is67.77% and body crossesEMA10, but closing location is32.23% from low: outside bottom25%. Thus this change alone still rejects that candle. This is intentional to avoid changing two independent filters.

## Extract into ~/RB-ITOS-AI and start with7August

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-body-cross-research/test_cross.py

PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-body-cross-research/batch.py \
  --input-zip data/research/hilega-one-minute-input-20261022/timing-input.zip \
  --session-input data/research/hilega-one-minute-input-20261022/session-input.json \
  --date 2026-08-07 \
  --output data/research/hilega-body-cross-20260807

.venv/bin/python hilega-body-cross-research/compare.py \
  --old-root data/research/hilega-body-breakout-aug-sept-oct \
  --new-root data/research/hilega-body-cross-20260807

cat data/research/hilega-body-cross-20260807/three-policy-summary.md
cat data/research/hilega-body-cross-20260807/three-policy-signals.md
cat data/research/hilega-body-cross-20260807/new-signal-values.md
```

Confirm tests and first-day replay succeed before widening. Baseline must pass. Connection failure/incomplete data are not zero-profit sessions.

## Widen to same three months

Use tmux to avoid SSH disconnection interrupting the replay:

```bash
tmux new -s bodycross
cd ~/RB-ITOS-AI
set +e
mkdir -p data/research
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-body-cross-research/batch.py \
  --input-zip data/research/hilega-one-minute-input-20261022/timing-input.zip \
  --session-input data/research/hilega-one-minute-input-20261022/session-input.json \
  --month 2026-08 --month 2026-09 --month 2026-10 \
  --output data/research/hilega-body-cross-three-months \
  > data/research/hilega-body-cross-three-months.log 2>&1
result=$?
echo "Replay exit code: $result"
tail -30 data/research/hilega-body-cross-three-months.log

.venv/bin/python hilega-body-cross-research/compare.py \
  --old-root data/research/hilega-body-breakout-aug-sept-oct \
  --new-root data/research/hilega-body-cross-three-months
```

Detach tmux with Ctrl+B then D; return with `tmux attach -t bodycross`. Repeating the exact command reuses valid completed daily cache entries; changed input/code invalidates the cache.

Outputs:
- three-policy-summary.md: deployed vs old BODY50 vs new body-cross daily points.
- three-policy-signals.md: setup, direction, entry/exit, route and winning/losing points side by side.
- new-signal-values.md: new trades with priceEMA10, body percentages, RSI/EMA/WMA and breakout price.
- daily-reports/YYYY-MM-DD.md: all recorded5m decisions plus1m waiting/breakout/cancellation records.
- YYYY-MM-DD.json: full audit and evidence for manual validation.

Compare excludes incomplete sessions and baseline trade mismatches. Matching baselines does not independently prove identical raw inputs: use the same input archive/session file as the original experiment. Trades can change strategy state and later setup identities; setup totals are not isolated causal attribution. Prices are historical candle-based NIFTY marks, not executable option fills; no costs. Do not promote based on one day.
