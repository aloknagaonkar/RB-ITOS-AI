# Research: bearish body-cross OR already-below continuation

October 26 only. No production code/config/services/orders changed. New standalone folder. Sources were AST syntax-parsed only; tests and full replays must run on your VM.

## Exact extension

Bearish candidate: completed red signal candle; abs(close-open)/(high-low) > 0.60; signal-time EMA10 < previous signal-time EMA10; AND either:

- BODY_CROSS: close < EMA10 < open (original route), OR
- BEARISH_ALREADY_BELOW: close < open < EMA10 (new continuation route).

Continuing downward means a red body AND falling EMA10. No additional lower-low or previous-close threshold was introduced. Equality at EMA10 endpoints remains rejected. A wick reaching above EMA10 does not invalidate an otherwise wholly-below body; the rule is about the body. Bullish remains strict crossing with rising EMA10; no bullish already-above extension is added.

Everything after qualification is unchanged: later completed 1m close below fixed signal LOW confirms bearish entry, adverse original-signal midpoint close cancels pending. Midpoint protection ON uses later completed 1m close above fixed original signal range midpoint for bearish independent positions. Equality holds; wick touches do not exit. Earliest same-direction reference remains, qualifying opposite signals can replace/cancel it, one position, existing entry priority at shared 5m boundaries, no reused consumed signals. Fixed 14:55 cutoff with exact minute-open pricing. Existing 5m entry route and exits remain enabled and unchanged. Existing-route trades do not receive independent midpoint protection.

A newly eligible candle is NOT an automatic entry. Specifically the 09:15 1m candle can qualify under the extension, but its next minute close is above its midpoint and cancels waiting. The 09:17 1m candle can form a later eligible reference. These facts are rule/input diagnostics, not a claimed full-state replay result.

## Full-state comparison

13 policies: existing 5m control, six STRICT runs (1m/3m/5m signal × protection OFF/ON), six EXTENDED runs. EMA10 is 10 candles at the signal interval; both variants use identical seeds/input. Signal intervals anchored at 09:15, later confirmation/protection always 1m, existing policy always 5m. Last complete 3m signal bar ends 14:54; no partial bar added.

Original uploaded October26 input SHA256 values are pinned. Every STRICT trade signature and the existing control must reproduce your previously uploaded results; mismatches block reporting. Recorded-bar reproduction must pass; API-versus-live parity is separately retained (known FAIL for the later API data). This never claims recovery of original live minutes.

## VM commands

Save ZIP to ~/RB-ITOS-AI. Extract NEW folder, then run tests:

```bash
cd ~/RB-ITOS-AI
unzip hilega-body-cross-continuation-20261026.zip

PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-body-cross-continuation/test_independent.py \
  hilega-body-cross-continuation/test_midpoint.py \
  hilega-body-cross-continuation/test_timeframes.py \
  hilega-body-cross-continuation/test_continuation.py
```

Only after tests pass:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-body-cross-continuation/run.py \
  --input-zip data/research/hilega-timeframe-input-20261026/timing-input.zip \
  --session-input data/research/hilega-timeframe-input-20261026/session-input.json \
  --output data/research/hilega-body-cross-continuation-20261026
```

Source hash mismatch or missing warmup blocks; do not bypass it. Default cache roots are the same three used earlier; an extra can be supplied via --cache-root. Existing output directory blocks; use a fresh --output if rerunning. Extraction does not require overwriting any old research folder or installed backend file.

## Outputs

- results.zip: upload this completed replay output.
- report.html: all 13 policies, entries/exits, original signal midpoint, qualifying route, peak profit/time and giveback; full audit values.
- report.json: complete trades/audits with peak and giveback values.
- extension-deltas.md: strict vs extended full-day gross points, each signal interval and protection mode.
- comparison.md: all-policy summary.
- manifest.json, strict-regression.json, recorded-bar-parity.json, api-live-parity.json.
- On failure: failure.json and available checks; no performance claim made.

Peaks use completed 1m closes after entry through actual exit, floored at zero; giveback = peak − final P&L. Hindsight peaks are not assumed fills or an achievable portfolio. Gross NIFTY index marks exclude fees, options, slippage and latency. No production promotion follows from one session. Full-state changes may create different later entries, so ON/OFF deltas are not merely matched-trade exit savings.
