# Current strategy on 1m / 3m / 5m — 26 October 2026

Package revision: 1.1.0-session-filter.

Research only. No installer, live source changes, service restarts, order transport,
credentials, broker/API requests or control-state changes. All tests/replay must
run on your Ubuntu VM. Author validation is source inspection and Python AST
parsing only. No local tests, strategy execution, replay or performance result.

## Inputs inspected

The supplied capture has 375 one-minute candles for 26 October 2026, captured at
21:50:57 IST, 636 audit rows, and 68 five-minute decisions from 09:20 to 14:55.
The six supplied current strategy modules match the latest earlier snapshot and
policy version `bullish-gap2-full-wma2-2.0.0-wma40-reversal`.

The carried archive has 513 nonempty warmup sessions ending 21 October. It lacks
22 and 23 October. The first recorded 5m frame's seeded count is 38,626, which is
consistent with 515 prior full sessions, two more than the carried archive.
This is a data-read observation, not replay validation. The runner adds newer
saved sessions from the installed historical cache directories, in their existing
root precedence. It never overwrites the carried archive or cached candles.
If 22/23 October cannot be loaded, it blocks before replay. Supply an additional
`--cache-root /absolute/directory` containing `2026-10-22.json` and
`2026-10-23.json` if needed. Files use the existing cache schema: session_date,
underlying (NSE_INDEX|Nifty 50), and candles with timestamp/open/high/low/close/volume.
No API recovery is performed by this package.

## Run on Ubuntu VM

Extract the ZIP in `~/RB-ITOS-AI`; it creates a new folder
`hilega-timeframe-research/`. Do not replace backend/frontend sources.

```bash
cd ~/RB-ITOS-AI
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-timeframe-research/test_cases.py
```

Only after the tests pass:

```bash
cd ~/RB-ITOS-AI
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-timeframe-research/study.py \
  --input-zip data/research/hilega-timeframe-input-20261026/timing-input.zip \
  --session-input data/research/hilega-timeframe-input-20261026/session-input.json \
  --output data/research/hilega-timeframe-results-20261026
```

Use tmux for long research runs. Run one replay at a time. The 1m run recomputes
all prior-session warmup and can take substantial time. Outputs use a NEW
nonexistent directory; after a failed run choose a new output path (for example
`...-retry1`) instead of deleting the diagnostic evidence.

Share the first error if tests fail. If replay blocks, share `failure.json` and,
when generated, `parity.json`. No source hash, input, warmup or parity gate should
be bypassed. No lower-timeframe comparison is produced after a failed 5m control.

## Experiment definition

The installed 5m strategy is the control. The 1m/3m variants use temporary isolated
copies of the six source modules whose SHA256 hashes are pinned in this package.
Same RSI9 Wilder, EMA3 RSI, WMA21 RSI, price EMA10 counts and numeric thresholds;
their elapsed-time lookbacks and per-bar strength/slope horizons change. This is
a full strategy cadence comparison, not unfinished 5m indicators sampled earlier.

Bar spacing, full-WMA references, followup timing, opening stages and policy frame
availability change to the selected cadence. The policy's one-minute sentinel
used to represent the minute immediately before a decision remains one minute.
Bullish gap>=2/full WMA>=2, touch waiting, qualified opposite override, bearish
WMA>40 exit permission and confirmed bullish reversal remain. 14:55 cutoff remains.
Only completed bars anchored at 09:15 are consumed; last completed 3m candle before
cutoff ends 14:54. No unfinished 3m candle is invented at 14:55. Hypothetical entries
and normal exits use completed-candle closes, not executable option fills; cutoff
uses the observed exact 14:55 minute open. Fees/slippage/latency are excluded.

The 5m control must match all 68 recorded decision frames (OHLC, current/prior
indicators, price EMA and seed count), version, directional entries/exits, prices,
points and cutoff coverage. Conflicting duplicate evidence fails. This validates
reproduction of the supplied recorded extract; it is not cryptographic audit
verification, independent chart parity, broker-fill evidence or production approval.
Later API candles can differ from original live candles; a difference blocks.

## Early direction

Outputs separate raw SETUP candidates, fully confirmed ENTRY events, and onset of
simultaneous same-direction active ownership on 1m+3m. A SETUP is informational,
not a confirmed trade. Setup alerts stop being valid when discarded/superseded;
if they become a trade, their lifetime ends with that trade. Entry and agreement
alerts stop at an exit/opposite change. No new strategy filters are introduced.

Primary matching window is fixed before analysis: the next 5m boundary. Only
strictly earlier, off-5m-boundary alerts count. Match same direction while valid,
strictly before its invalidation time. Each 5m entry matches at most one alert per
stream; earliest valid alert wins. Other streams are independent comparisons.
A missing/unused match is not proof of a losing trade. Matching is temporal and
directional, not proof of the same setup identity across indicator timeframes.
Agreement is generated causally when both lower-timeframe owners are active,
never backdated to their earlier entry. Future 5m outcomes only label prior alerts.

## Outputs

- `comparison.md`: trade totals, points, closed-trade drawdown, alert rates/lead.
- `early-direction.md`: every alert, next boundary, confirmation/failure category,
  matched 5m entry, lead minutes and directional price advantage.
- `trades.md`: all three strategies' setup/qualified/entry/exit/points/reasons.
- `decision-audit.md`: every completed-boundary frame, setup/check, entry/exit,
  pending identity, policy events and confirmed bullish reversal monitor evidence.
- `report.json`: complete underlying results and early-alert data.
- `parity.json`, `manifest.json`: reproduction proof and source/input/cache hashes.
- `results.zip`: all the above, ready to upload here for interpretation.

A one-session result cannot establish broader reliability. No comparison has been
executed by the author. The recorded baseline summary included in this package is
read directly from the uploaded audit and labelled accordingly.

## Revision 1.1.0: historical post-close rows

The supplied archive contains 10 post-close rows at 15:39 and 15:59 IST on
25 April, 30 April, 8 May, 13 May and 21 May 2025. Original session aggregation
never consumed these rows. Revision 1.0 incorrectly rejected them before
aggregation. Revision 1.1 validates all warmup row schemas/dates/duplicates,
then excludes out-of-session warmup rows and records each timestamp in
manifest.json / warmup_input_actions. All 375 regular minutes remain required.
The target session retains strict regular-session validation. No candle is
filled, shifted or synthesized. Original ZIP/cache bytes remain unchanged.
Tests and replay have not been executed locally.
