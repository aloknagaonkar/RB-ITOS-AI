# OI Fallback Semantic Overlap Diagnostic V1

## Why this exists

`OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1` prefers positioning OI and can fall back to option-OHLC `open_interest` for an exact timestamp/strike/side when positioning OI is unavailable.

Because fallback usage is high on the current research dates, this diagnostic tests whether the two fields behave as the same measurement **where both sources overlap exactly**.

It does not alter the audit, strategy, thresholds, or signal generation.

## Exact comparison key

A comparison is made only when both sources have:

- the same timestamp
- the same physical strike
- the same CE/PE side

No nearest timestamp, nearest strike, interpolation, synthetic fill, or forward/back fill is allowed.

## Per-overlap output

For every exact overlap:

- positioning OI
- option-OHLC OI
- signed difference = OHLC - positioning
- absolute difference
- relative difference vs positioning
- exact-match flag
- within 0.1%, 0.5%, 1%, and 5% flags

If positioning OI is zero, percentage differences are reported as `None` instead of infinity.

## Session summary

Reports:

- observation counts in each source
- exact overlap count
- source-only counts
- overlap coverage vs positioning
- exact-match rate
- within 0.1%, 0.5%, 1%, 5% rates
- mean/median absolute difference
- mean/median absolute relative difference
- mean signed difference and bias direction
- CE/PE-specific statistics

The diagnostic intentionally does **not** define an acceptance threshold yet. Acceptance criteria must be chosen only after observing multiple frozen dates, not tuned on one date.

## Run on the three current frozen dates

Use the exact cache paths printed by each V1.1 audit. Based on the current runs:

```bash
python -m backend.market_lab.oi_fallback_semantic_overlap_diagnostic_v1 \
  --input '2026-05-12:data/historical-positioning-cache-oos-d/NSE_INDEX_Nifty_50__2026-05-12__2026-05-12__w5.json:data/historical-option-ohlc-cache-oos-d/NSE_INDEX_Nifty_50__2026-05-12__2026-05-12__w5.json' \
  --input '2026-05-18:data/historical-positioning-cache-oos-c/NSE_INDEX_Nifty_50__2026-05-18__2026-05-19__w5.json:data/historical-option-ohlc-cache-oos-c/NSE_INDEX_Nifty_50__2026-05-18__2026-05-19__w5.json' \
  --input '2026-08-25:data/historical-positioning-cache-*/NSE_INDEX_Nifty_50__2026-08-25__*__w5.json:data/historical-option-ohlc-cache-*/NSE_INDEX_Nifty_50__2026-08-25__*__w5.json' \
  --overlap-csv data/historical-evidence/oi-fallback-semantic-overlap-v1.csv \
  --summary-json data/historical-evidence/oi-fallback-semantic-overlap-summary-v1.json
```

Important: shell wildcards inside the quoted `--input` values are not expanded by this V1 tool. For Aug 25, replace the `*` entries with the exact positioning and option-OHLC paths printed by the Aug 25 V1.1 audit before running.

## Research interpretation

A high overlap-match rate would support using OHLC OI as a fallback measurement.

Large or systematic differences would mean the fallback should not be treated as interchangeable until the data semantics are understood or the audit is changed.

Neither outcome changes trading logic automatically.
