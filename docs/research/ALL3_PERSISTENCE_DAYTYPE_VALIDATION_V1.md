# ALL3_PERSISTENCE_DAYTYPE_VALIDATION_V1

Frozen research hypothesis:

- Bullish days: longer BULLISH_ALL_3 persistence, shorter bearish counter-runs.
- Bearish days: longer BEARISH_ALL_3 persistence, shorter bullish counter-runs.
- Mixed/reversal days: more balanced persistence.

This study uses the already-frozen ALL_3 definition and day labels only for evaluation.
It does not alter P1/P2, the strategy, or the state definition and does not tune run thresholds.

The built-in cohort is 18 frozen bullish + 18 frozen bearish sessions.
Per session it records run count, total directional candles, mean/median/max run length,
1-candle runs, 2-candle runs, 3+ runs, directional shares, and dominant-vs-counter persistence.

No mixed/reversal dates were previously frozen, so V1 does not invent any. Pre-frozen mixed
dates can be added with --labels-csv containing: session_date,day_type where day_type is
BULLISH_DAY, BEARISH_DAY, or MIXED_REVERSAL_DAY.
