# Normal Route

Independent research strategy `NORMAL_ROUTE`, display name **Normal Route**,
version `normal-route-rsi5-ema30-0.3.0`. It does not change the deployed Hilega app.

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -u -B normal-route-research-v1/run.py \
  --days 2026-11-20 2026-11-23
```

## Entry: all eight conditions on the same completed 3-minute candle

| Condition | CE | PE |
|---|---|---|
| Price | Close > EMA30 High | Close < EMA30 Low |
| Candle colour | Green: close > open | Red: close < open |
| RSI5 | >55 | <45 |
| RSI9 | >55 | <45 |
| RSI14 | >55 | <45 |
| RSI21 | >55 | <45 |
| RSI28 | >55 | <45 |
| WMA21 of RSI9 | >50 | <50 |

Doji candles are rejected. RSI28 is an entry filter only. All RSIs use Wilder
smoothing on closes, with continuous cross-session indicator history. WMA21 is
calculated from RSI9, not RSI28 or price. EMA30 High/Low use the completed 3m
high/low series, alpha 2/31 and first-value seeding across 20 verified prior
sessions. RSI9/WMA21 parity against the current indicator fixture is retained.

## Exit: all three groups together; no latching across candles

| Group | CE exit | PE exit |
|---|---|---|
| Momentum | RSI5 <50 AND RSI9 <50 | RSI5 >50 AND RSI9 >50 |
| WMA | WMA21(RSI9) <50 | WMA21(RSI9) >50 |
| Price | Close < EMA30 Low | Close > EMA30 High |

All three groups must be true on the SAME completed candle. Otherwise hold.
The mandatory 15:30 close is independent. Equality at a threshold does not pass.
No extra EMA10, WMA-strength vote, slope, follow-up wait, hard stop or target is
included. The entry conditions are state checks, not mandatory fresh crossovers.

## Inputs, fills and reports

Fresh calculations read existing verified target candles and exactly 20 verified
prior sessions; RSI28 is recomputed from those closes, not inferred from RSI21.
Old RSI4 audit uploads without RSI28 cannot establish Normal Route trade results.
Missing/invalid inputs are reported explicitly. The runner does not fetch market
data, install source, restart services, modify caches, alter live journals or
submit broker requests.

Normal fills use the next minute OPEN at the completed-candle boundary. The 15:30
exit uses exact 15:29 close. No entry at 15:30. Exit precedes a qualified opposite
entry at the same boundary; one position at a time. Reports show simulated NIFTY
points, not option-premium returns, fees, slippage, strike selection or execution.
Held 1m highs/lows yield peak-positive points; giveback = peak minus final points.
Peaks are hindsight excursions, not guaranteed achievable profits.

Outputs use a new timestamped `data/research/normal-route-*` folder. The terminal
prints every trade with entry/exit RSI28 and other indicators, points, peak and
giveback. The ZIP includes full JSON, trade CSV, both-direction per-candle CSV and
offline HTML with all eight entry checks and active exit flags. Route name/id
are included in JSON, trades and CSVs. Source and warmup hashes are preserved.

Run checks separately if desired:

```bash
.venv/bin/python -B -m unittest discover -s normal-route-research-v1/tests
```

Twelve tests cover naming, all eight gates, RSI28 readiness/thresholds, green/red
and doji handling, unchanged RSI9/WMA21 parity, all exit-group truth combinations,
strict boundaries, fills, reversal ordering, independent session close and HTML.
