# Frozen confirmed-midpoint RSI strategy — October 2026

Standalone research runner; not an installer. Strategy version rsi-two-route-0.5.1-confirmed-midpoint-research. engine.py is byte-identical to the November confirmed-midpoint research engine that produced 60 trades and +1765.25 NIFTY points; all 16 recorded November sessions were reproduced before packaging. No October tuning has been performed.

## Run on VM

From ~/RB-ITOS-AI:

```bash
.venv/bin/python -u -B rsi-confirmed-midpoint-v1/run.py \
  --month 2026-10 --through 2026-10-31 \
  --recover-missing --export-inputs
```

Reviewed calendar expects 20 regular October sessions and 11 non-trading dates. Each target requires exactly 20 preceding reviewed sessions: earliest seed needed for 1 October is 2 September 2026. All inputs are raw 1m candles; indicators recomputed independently for each session. No existing trade results reused.

--recover-missing uses the existing Upstox access token from environment/.env only for historical-candle reads. Missing or invalid inputs are recovered into the new research output folder; original caches are never overwritten. No order transport is created by this runner. It does not restart services, install source, change configurations, trade records or live journals.

--export-inputs includes copies of all required validated target/seed source JSON files in verified-inputs/ inside the result ZIP. It fingerprints and replays those exact copied bytes for both variants. Newly recovered files are retained there too. No access token or .env file is exported. If all caches are complete, --recover-missing may be omitted. Without it missing or invalid sessions are explicit failures. Source-recovery requests may take time; each recovered date is printed.

Missing/invalid/recovery failures are reported per date/model, results and ZIP still generated, exit status 2. Never interpret a failed date as a zero-trade success. Empty/missing token with --recover-missing fails before replay, without broker execution.

## Frozen entry rules — completed 3m candles

Common CE: green close>open, close>EMA30 High. PE: red close<open, close<EMA30 Low. No body or wick limits, no extra follow-up candle, no fresh-setup re-entry lock.

Normal Route: common gates AND at least two of RSI5/9/14/21/28 strictly >55 CE / <45 PE, AND WMA21(RSI9)>50 CE / <50 PE.

WMA_bypass: common gates AND all five RSI thresholds pass. WMA threshold waived, not data readiness. Normal Route takes priority. All indicators must be available; doji fails colour.

## Frozen exit rules

- Mandatory 15:30 close; no re-entry at session close.
- A fully qualified opposite entry through either route independently exits the held position then enters the opposite direction.
- Additional protective exit: CE completed close < fixed initial signal candle (High+Low)/2 AND RSI5<50 AND RSI9<50. PE mirrored close > midpoint AND RSI5>50 AND RSI9>50. Same completed candle; no latched confirmations. Wick-only breach/equality do not trigger.
- Original all-three exit remains: CE (RSI5<50 AND RSI9<50) AND WMA21(RSI9)<50 AND close<EMA30 Low; PE mirrored >50 and close>EMA30 High.
- Priority: session close, opposite-entry reversal, confirmed midpoint exit, original all-three exit.
- No same-candle same-side entry after a confirmed midpoint breach. Subsequent qualifying candles may re-enter. Same-side signals while held do not add positions.

Ordinary signals use completed bars only; simulated fills use next 1m open. Final close exact 15:29 close. MFE from held minute highs/lows, entry inclusive/exit exclusive. Giveback=MFE-final points. No option premium fills, transaction costs or slippage; summed peaks are not a realizable portfolio return. Single owner, no overnight positions.

## Comparison and artifacts

UPDATED is the frozen confirmed-midpoint setup. BASELINE is the same two entry routes and original/reversal exits, WITHOUT the added midpoint-RSI exit (not the old all-five-RSI entry version).

Outputs under data/research/rsi-confirmed-midpoint-<timestamp>:
- audit.html: confirmed-midpoint strategy, date/direction/route/day-trend filters, per-trade indicators and every completed candle's checks/blockers/events/exit evidence.
- baseline-audit.html: same entry rules with control exits, separate totals.
- comparison.html: monthly and daily before/after results.
- results.json: all audits, strategy versions, input/code SHA256, coverage, recovery dates, net/gross gain/loss, worst trade, closed-trade drawdown, peak/giveback.
- daily-summary.csv, trades.csv and candle-audit.csv.
- verified-inputs/*.json with --export-inputs (recovered files retained even without export).
- sibling ZIP containing all result files recursively, including exported inputs.

Day trend is descriptive full-session close versus open and never a strategy gate. Repeated-month comparison is research, not broker execution validation. No October performance is claimed by this package before VM replay.

## Checks

`python3 -m unittest discover -s rsi-confirmed-midpoint-v1/tests -v`

29 local checks passed: routes/votes/strictness/readiness, retained colour without strength limits, mirrored midpoint+RSI exits, equality/wick rejection, no latched votes, same-candle re-entry control, reversal/session priorities, indicator parity, HTML filters, CLI partial-failure exports, input recovery and source preservation, full October date range. Additionally, frozen engine byte identity and 16-session/60-trade November supplied-frame parity passed. Tests use synthetic candles/previous uploaded frames, not actual October input candles.
