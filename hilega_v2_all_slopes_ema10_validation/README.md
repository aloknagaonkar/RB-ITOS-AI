# Five-minute all-three slopes and price EMA10 validation

Research runner only; no installer, broker calls, live strategy changes or Sandbox changes.

Extract folder under RB-ITOS-AI and run:

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_v2_all_slopes_ema10_validation/run.py --self-test &&
PYTHONPATH=backend:. .venv/bin/python hilega_v2_all_slopes_ema10_validation/run.py --end-date 2026-10-09
```

Default evaluates July 10–October 9 and reports overlapping one/three-month windows by direction. Output: data/historical-evidence/hilega-v2-all-slopes-ema10-validation-v1. Choose a fresh --output-root for reruns. Local results included cover September 10–October 9 only. Missing/empty cache dates remain explicitly reported, not assumed holidays.

## Rules

Every entry and non-cutoff exit uses a completed five-minute candle. A 09:15 label is available at 09:20. Slopes = current completed indicator minus previous completed indicator. RSI9, EMA3-on-RSI and WMA21-on-RSI slopes must ALL be positive for bullish entry, ALL negative for bearish entry; equality waits.

Existing strict5m setup remains: fresh canonical V1 entry OR first aligned, positive expanding-gap candle in an alignment episode. Entry also requires RSI9 > EMA3 > WMA21 bullish, inverse bearish; directional EMA3/WMA21 gap >0 and expanding versus previous completed bar. No one-minute provisional indicator, persistence check, pending ten-minute window or calibrated numeric strength floor is added. Rejected alternative consumes its episode; fresh canonical setup or break/re-form of alignment required. Previous-session last completed indicator is the reference for the first candle, explicitly labeled in audits.

All variants use bullish exit only when RSI9 AND EMA3 are below WMA21 AND all three slopes falling; bearish exit only when RSI9 AND EMA3 above WMA21 AND all three slopes rising.

- BASELINE: current installed V2, unchanged rules; warmup optimized with result parity verified.
- ALL_SLOPES_5M: entry and exit as above.
- ALL_SLOPES_5M_EMA10_ENTRY: above plus bullish Nifty close > five-minute PRICE EMA10, bearish close < EMA10.
- ALL_SLOPES_5M_EMA10_ENTRY_EXIT: above plus bullish exit close < EMA10, bearish exit close > EMA10. This is AND with every slope/indicator exit condition, not an independent exit trigger or a latched warning condition.

EMA10 is on Nifty price closes, alpha 2/11, seeded with first available close, continuous across prior sessions; at least ten completed warmup bars required. Current completed close contributes before comparison. It is separate from EMA3 on RSI.

Cutoff14:55 exact minute OPEN overrides every filter; no entry then. Else exit first before same-boundary replacement. One active position maximum. No PCR, Midpoint, time blacklist, strength075, stop-loss or profit-protection added.

Audits contain previous/current indicator values, all-three slope values, gap and delta, price EMA10, entry/exit condition booleans and reasons for rejection. CSVs: summary, daily, trades, losses, attribution, coverage; full candle audits: sessions/<date>/<policy>.json.

## Performance change

Within one runner process, earlier-session canonical warmup and price EMA10 update incrementally once and are deep-copied before each variant. Target session processing cannot mutate shared warmup. Inputs must remain unchanged during a run. Non-prefix warmup requests reset cache. Each target date still undergoes full variant lifecycle replay; no post-filtering completed trades. Baseline trades checked against unoptimized prior outputs for all 20 local sessions.

Nifty points before fees, slippage and option fills. Reconstructed cache inputs; no verified live/chart indicator parity or independent out-of-sample claim. Historical thresholds/filters can give back gains; evaluate full VM three-month run before deployment.
