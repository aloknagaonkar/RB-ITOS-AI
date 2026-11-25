# RSI two-route research v1

Strategy: `rsi-two-route-0.4.0-strong-candle-reversal`.

This is a standalone research runner, not an installer. It never changes live strategy modules, service state, existing caches or trading journals and never connects to a broker. Run from RB-ITOS-AI with its existing verified candle caches and bounded warmup module:

```bash
.venv/bin/python -u -B rsi-two-route-v1/run.py --month 2026-11 --through 2026-11-23
```

This recomputes BOTH updated strategy and original November baseline on the same raw 1m candles, with exactly 20 verified prior sessions per date. It does not load existing trade results. Default scope is 1–23 November, not future November sessions. Missing/invalid inputs are explicit failures, not zero-trade successes; the ZIP is still written, with exit code 2 for partial failure. No network fetch is attempted.

## Updated entry rules

Both directions use completed 3m signal candles. Common mandatory gates:
- CE: green close > open, close > EMA30 High.
- PE: red close < open, close < EMA30 Low.
- Body >=70% of high-low range; upper wick <=15%; lower wick <=15%.
- Doji, invalid/zero range candles fail. All indicator values must be available; bypass waives the threshold, not data readiness.

RSI periods: 5,9,14,21,28. CE RSI pass is strictly >55; PE pass strictly <45.

Normal Route: common gates AND at least 2/5 RSIs pass AND WMA21(RSI9) >50 (CE) or <50 (PE).

WMA_bypass: common gates AND all 5/5 RSIs pass; no WMA threshold requirement. Normal Route has priority if both routes qualify. Therefore bypass is selected when the normal WMA threshold fails, including WMA exactly 50.

All gates are evaluated on the same completed candle, no latched votes, slopes, extra wait or Hilega filters. Threshold equality fails strict RSI/EMA/WMA tests. Body/wick thresholds are inclusive (a tiny floating point tolerance only at exact limits).

## Updated exits / reversals

1. At 15:30 close the position and never re-enter.
2. Before session end, a qualified opposite entry through either route independently closes the held position and opens the opposite direction at the same simulated boundary fill. Exit recorded before entry, reason QUALIFIED_OPPOSITE_ENTRY. No extra confirmation candle. Weak or unqualified opposite candles do not cause this reversal.
3. Otherwise the original all-three exit applies: CE RSI5<50 AND RSI9<50 AND WMA21(RSI9)<50 AND close<EMA30 Low; PE mirrored >50 and close>EMA30 High. All groups on the same completed candle. RSI14/21/28 are not exit gates.
4. Same-direction signals retain the existing trade, no duplicate entries. One position at a time.

The runner is a simulator. A future broker implementation must confirm exit execution before placing the new position; this bundle does not implement or enable order submission.

## Fill and calendar model

Completed 3m signals, next 1m open simulated NIFTY entry/ordinary exit. Session close uses exact 15:29 minute close. MFE uses held 1m high/low (entry inclusive, exit exclusive); giveback = MFE - final directional points. No option premium fills, fees or slippage. Summed trade peaks are not an achievable portfolio return.

Regular days strictly use 125 bars. 8 November uses 23 complete bars starting 14:21 after excluding the incomplete 14:20 leading minute; first decision 14:24, final close 15:30. Reviewed calendar is inherited from deployed warmup module.

## Comparison baseline

`baseline.py` is byte-identical to the previous normal-route-november-v1 engine, version normal-route-rsi5-ema30-0.3.0. It requires all five RSI thresholds, WMA, candle colour and EMA30 position, with no strength/wick requirements and no independent opposite-entry exit. This preserves the previously reported +1081.60 point November result as a comparison target when the input hashes are identical. The new result is NOT known until this runner executes on VM data.

## Outputs

Under data/research/rsi-two-route-<timestamp>, printed at completion:
- audit.html: updated date, bullish/CE or bearish/PE, descriptive day-trend and entry-route filters; recalculated trade totals; all 3m audits with both-side raw rules, RSI vote count, selected route, per-route blockers, strength percentages, ownership, exits and accepted events. Route filter applies to trades/totals; all candle diagnostics stay available. Individual failed RSI/WMA checks do not block a route when its aggregate gates pass.
- baseline-audit.html: original baseline with its own separate totals.
- comparison.html: both monthly summaries and daily before/after totals.
- results.json: both models, full audit and input/code SHA256 evidence, coverage and failure status.
- daily-summary.csv, trades.csv, candle-audit.csv; matching output ZIP.

Day trend is full-session close versus open, a descriptive after-session label only, not used in entry logic. Missing days are not treated as profitable or zero-trade validations.

## Checks

`python3 -m unittest discover -s rsi-two-route-v1/tests -v`

18 tests passed locally, including all RSI pairs in both directions, WMA bypass/priority/readiness, strict thresholds, body and wick boundaries, independent opposite-entry reversal in both directions, no duplicate entries, no weak-candle reversal, unchanged exits and indicators, session close priority, short session, HTML controls and JavaScript filter totals, and CLI export/partial-failure handling. Node is needed only for the JavaScript test. Synthetic tests validate behavior, not historical performance. Actual November replay requires VM data.
