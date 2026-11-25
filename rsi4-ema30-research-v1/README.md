# New RSI strategy — independent 3-minute research

Run a fresh calculation on verified VM candles:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -u -B rsi4-ema30-research-v1/run.py \
  --days 2026-11-20 2026-11-23
```

No app install, source/pin changes, service restarts, broker requests or cache
writes. Only new timestamped reports under `data/research/rsi4-ema30-*`.
The runner uses existing target caches and exactly 20 verified prior sessions;
missing/invalid inputs fail explicitly instead of being fetched or substituted.
It recalculates the new strategy rather than reading Hilega's saved trade results.

## Entry — all six conditions at the same completed candle

| Condition | CE | PE |
|---|---|---|
| Price close | > EMA30 of 3m High | < EMA30 of 3m Low |
| RSI5 | >55 | <45 |
| RSI9 | >55 | <45 |
| RSI14 | >55 | <45 |
| RSI21 | >55 | <45 |
| WMA21 of RSI9 | >50 | <50 |

RSIs use Wilder smoothing and closing prices. RSI9/WMA21 values have been checked
against the current Hilega indicator implementation at 12-decimal precision on
a non-monotonic fixture. EMA30 High and Low use alpha 2/31, seeded from the first
warmup high/low. All indicators continue across sessions; positions reset daily.
Warmup includes the reviewed shortened-session complete-bar policy.

There is no crossover requirement, no extra signal follow-up, colour filter,
WMA-strength vote, EMA10 condition or other Hilega entry restriction.

## Proposed exits being tested

Default BALANCED: CE exits when RSI5 AND RSI9 are below 50; PE exits when both
are above 50. Independently, CE exits on close below EMA30 Low; PE on close above
EMA30 High. Positions close at 15:30 regardless. Threshold equality does not
trigger an indicator entry/exit. WMA50 is an entry filter, not an exit gate.

Optional comparisons:

```bash
.venv/bin/python -u -B rsi4-ema30-research-v1/run.py \
  --days 2026-11-20 2026-11-23 --variants BALANCED FAST WMA
```

FAST uses RSI5 alone beyond 50 for momentum exit. WMA uses RSI9 below/above its
WMA21. Opposite EMA-boundary and session-end exits stay identical in each variant.
Variants are research hypotheses, not proven profitable rules.

## Execution assumptions and outputs

Signals occur when each exact completed 3-minute bar becomes available. Entry and
normal exit fills use the next 1-minute OPEN at that boundary, not the just-closed
candle price or the next minute's future close. Example: 09:15–09:17 candle,
09:18 signal, simulated fill at 09:18 open. Session exit uses exact 15:29 close
with 15:30 exit time. No entry at 15:30. One position at a time; exit is processed
before a fully qualified opposite entry on the same boundary. Re-entry is allowed
when flat and conditions qualify again.

These are directional NIFTY spot points representing CE/PE signals. They do not
include option premiums, strike selection, spreads, fees, slippage, intrabar stops
or broker execution. Peak positive points use held 1-minute highs/lows, exclude
the pre-entry signal bar and the post-exit minute, and are hindsight excursions.
Giveback = peak positive points minus final directional points.

The terminal prints all trades with entry/exit indicator values and reasons.
The result ZIP contains `results.json`, `trades.csv`, `candle-audit.csv` and a
self-contained `audit.html` with both directions on all 125 completed candles.
Checks while a position is held describe qualification, not an additional entry.
Only accepted ENTRY events create simulated trades. Upload the printed result ZIP
for detailed analysis. Input paths, hashes, seed coverage and engine hash are
included. Non-trading dates are labelled explicitly; no adjacent date substituted.

## Verification

```bash
.venv/bin/python -B -m unittest discover -s rsi4-ema30-research-v1/tests
```

Tests cover canonical indicator parity, Wilder readiness, strict thresholds,
mandatory conditions, PE Low source, independent price/momentum exits, fill timing,
peak/giveback holding windows, session closure and exit-before-reversal ordering.
