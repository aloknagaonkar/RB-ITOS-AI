# Phase 6.3A2

Supplements the current-day directional recovery with exact recorded 1-minute
Nifty candles from:

`data/live-observation/hilega-directional-market-evidence-v1/<date>.jsonl`

The journal contains warmup and repeated responses, so extraction is based on
canonical candle identity rather than journal `kind`:

- exact target `session_date`
- exact `NSE_INDEX|Nifty 50`
- exact `interval_seconds == 60`
- exact recorded OHLC

Identical duplicates are deduplicated. Conflicting duplicate 1m candles or
conflicting 5m overlaps fail closed.

For Sep 24, rerun deliberately with `--force` because Phase 6.3A already wrote
the 61-row partial reconstruction.
