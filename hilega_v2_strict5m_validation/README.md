# Strict five-minute V2 validation
Research only. Does not install or enable a live strategy, change Sandbox, or contact Upstox.

Run from RB-ITOS-AI root after extracting this folder:

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_v2_strict5m_validation/run.py --self-test &&
PYTHONPATH=backend:. .venv/bin/python hilega_v2_strict5m_validation/run.py --end-date 2026-10-09
```

Default evaluates July 10–October 9 and reports overlapping one/three-month windows. A fresh output folder is required; use --output-root for reruns. Uses existing Nifty caches and all available earlier warmup dates. Missing/empty dates are reported, not assumed holidays. Local included results cover only September 10–October 9, and October 6–9.

## Exact rules

Only completed five-minute candles update indicators or evaluate orders. The 09:15 candle is available at 09:20. No provisional one-minute indicator, persistence wait, or carried ten-minute setup window.

Entry: a fresh canonical V1 entry setup OR the first positive expanding-gap candle in a continuous completed-five-minute alignment episode. Every entry must additionally satisfy strict RSI9 > EMA3 > WMA21 for bullish (inverse bearish), positive directional EMA3/WMA21 gap, gap expansion over preceding completed five-minute candle, and directional WMA21 slope. A rejected alternative consumes its episode; alignment must break and return, or a fresh canonical setup must arrive. There is no retrospective entry after rejection.

Bullish strength = current WMA21 minus previous WMA21. Bearish strength = previous WMA21 minus current WMA21. Entry uses WMA slope only, not all-three entry slopes. All three slopes are recorded. Previous/current indicators, gap, expansion, strength and rejection reasons are included for BOTH directions on every candle. The first session candle compares to the last completed prior-session candle; this overnight comparison is explicitly labeled.

Bullish exit: RSI9 AND EMA3 below WMA21 AND RSI9, EMA3, WMA21 all falling. Bearish exit: RSI9 AND EMA3 above WMA21 AND all three rising. Equality or mixed slopes waits. EMA10 is not included. At 14:55 exact minute OPEN, force exit regardless of slopes; no new entry. Else exit precedes any same-boundary new entry, with at most one active trade.

## Four policies

- BASELINE: installed V2 alignment/dual-exit engine, unchanged.
- STRICT5M_DUAL_EXIT: five-minute entry with WMA slope >0 directionally; existing dual-indicator exit.
- STRICT5M_ALL_SLOPE_EXIT: same entry plus mandatory all-three exit slopes.
- STRICT5M_ALL_SLOPE_EXIT_STRENGTH075: additionally require five-minute directional WMA change >=0.75. This is an experiment, not a calibrated replacement for the previous provisional-minute threshold.

No PCR, Midpoint filter, time-of-day blacklist, EMA10 or profit protection is added.

## Outputs

summary.csv: one/three-month performance by direction; daily.csv: date-wise results; trades.csv/losses.csv: entry/exit, reasons, checks, Nifty points; attribution.csv: matched/new/removed entries and net change; coverage.csv: incomplete dates; sessions/<date>/<policy>.json: full candle audit.

Reconstructed Nifty points exclude brokerage, slippage and options execution. No claim of live/chart indicator parity or independent out-of-sample validation. Slopes may postpone exit and increase giveback; compare full lifecycle results before deployment. Synthetic tests validate signs and rules, not profitability.
