# Independent body crossing +1m breakout — research only

This standalone research directory is additional to the existing route. It does not install or modify backend/frontend files, activate services or send orders. Source syntax was parsed locally; tests/replays were NOT run locally, per your preference. Run them on the VM.

| Stage | Bullish | Bearish |
|---|---|---|
|Independent setup|Completed5m green body >60% of high-low range|Completed5m red body >60% of range|
|Actual body cross|Open < priceEMA10 < Close|Close < priceEMA10 < Open|
|PriceEMA10 slope|Rising|Falling|
|Wick/body-endpoint touch only|Reject|Reject|
|Existing strategy setup event|Not required|Not required|
|Outer25% close / >50% beyondEMA|Not required|Not required|
|RSI/WMA/strength/gap filters for extra route|Not required|Not required|
|1m confirmation|Completed1m close > fixed signal high|Completed1m close < fixed signal low|
|Cancel waiting|Completed1m close < fixed signal midpoint|Completed1m close > fixed signal midpoint|
|Equality|Wait|Wait|

Midpoint is(high+low)/2, not body midpoint. Only completed candles. First possible confirmation is the next1m close after setup. Waiting has no fixed expiry, stops at cutoff; earliest same-direction reference is preserved. New qualifying opposite independent signal replaces waiting. Existing fully qualified opposite-watch event can also cancel waiting. One active position only; existing entry wins if it executes on the same5m boundary. Existing route remains active while flat. Independent route cannot add exposure or force a new reversal during an active trade.

After entry: unchanged deployed5m exits. Bullish bothRSI9 andEMA3RSI belowWMA21; bearish bothaboveWMA21 AND WMA21>40 OR fully confirmed existingbullish reversal.14:55cutoff overrides. No post-entry midpoint exit. No1m indicator recalculation.

## Existing-strategy support audit

At independent entry a separate same-direction existing-policy observer starts with current pending confirmation state and warmed indicators. Its canonical session is reset to flat, independently of the executed body-route position. This is a post-entry observational reconstruction, not a claim of exact baseline/live entries. Each5m its checks are saved. First fully confirmed same-direction existing entry emits EXISTING_STRATEGY_SUPPORTS_ACTIVE_TRADE with time, confirmation price, frame and checks. It never modifies quantity, independent entry time/price, P&L or execution state. The observer stops after confirmation or trade exit. It does not count an armed candidate or simple alignment as support. Actual deployed exits/reversal monitor remain separate.

##7August VM commands

Extract the folder into ~/RB-ITOS-AI. Do not replace other research directories.

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-independent-body-research/test_independent.py

PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-independent-body-research/batch.py \
  --input-zip data/research/hilega-one-minute-input-20261022/timing-input.zip \
  --session-input data/research/hilega-one-minute-input-20261022/session-input.json \
  --date 2026-08-07 \
  --output data/research/hilega-independent-body-20260807

.venv/bin/python hilega-independent-body-research/compare.py \
  --old-root data/research/hilega-body-breakout-aug-sept-oct \
  --new-root data/research/hilega-independent-body-20260807

cat data/research/hilega-independent-body-20260807/three-policy-summary.md
cat data/research/hilega-independent-body-20260807/three-policy-signals.md
```

For all availableAug/Sep/Oct sessions replace `--date2026-08-07` with `--month2026-08 --month2026-09 --month2026-10` using spaces after option names, and use a new output `data/research/hilega-independent-body-three-months`. Use tmux for the long run. Each completed date caches with source/input fingerprints; rerunning resumes valid entries. Comparison must use same input files as previousBODY50 experiment. Equal baseline trades alone cannot prove raw inputs identical.

Outputs:dailyJSON(fullaudit),daily-reports/date.md(all5m/1m checks/support),signal-values.md,three-policy-signals.md(entry–exit/points side by side),new-signal-values.md,three-policy-summary.md. Raw JSON policy key INDEPENDENT_BODY_1M_WAIT. Existing comparison key DEPLOYED_5M. Both remain hypothetical grossNIFTY points without optionfills/costs.

Expected structural effect:7Aug10:00–10:05 now qualifies a BEARISH independent setup without an existing bearish setup event. The replay must determine whether a subsequent completed1m close breaks the actual signal low24607.50 and midpoint24617.275 from the recorded candle. No profit result is claimed before VM replay.
