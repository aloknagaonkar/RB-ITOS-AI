Read-only 5m price EMA10 slope research.
python hilega_ema10_slope_validation/run.py --self-test
python hilega_ema10_slope_validation/run.py --date 2026-10-12

No installation or restart. Prior completed local caches warm the price EMA10 across sessions. Recovery caches take precedence. Missing warmup or target candles stop the calculation. Windows use chart opening labels, not decision availability timestamps. Exports per-candle and window CSVs, prints plain tables. No trading rules or orders changed.
