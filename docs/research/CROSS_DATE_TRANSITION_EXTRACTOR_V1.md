# Cross-Date Transition Extractor V1

## Purpose

Research-only aggregation over existing `OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1` JSON outputs.

This module does **not** create an entry rule, exit rule, regime state machine, trade signal, threshold optimizer, or parameter tuner.

It answers a narrower question:

> Across frozen historical dates, when do recent 5m / 10m / 15m option-OI imbalance and same-strike PCR change agree, and how long does that exact agreement persist?

## Descriptive horizon state

For each horizon independently:

- `BULLISH`: `imbalance_h > 0` **and** `pcr_change_h > 0`
- `BEARISH`: `imbalance_h < 0` **and** `pcr_change_h < 0`
- `MIXED`: values exist but do not agree
- `NA`: either required value is unavailable

The three-horizon state is:

- `BULLISH_ALL_3`
- `BEARISH_ALL_3`
- `MIXED`
- `INCOMPLETE`

No 2-of-3 threshold is converted into a directional state. Counts are retained separately so later research can inspect them without hard-coding a rule.

## Persistence

A persistence run is every consecutive sequence of exact `BULLISH_ALL_3` or exact `BEARISH_ALL_3` candles.

No minimum run length is imposed.

The run CSV records:

- session
- direction
- start timestamp
- end timestamp
- candle count

## Context retained but not merged into the state

- futures OI direction/status
- VWAP side
- fixed 09:20 session OI imbalance
- fixed 09:20 session PCR baseline/current/change
- fallback-used flag
- optional evaluation label

These remain independent fields deliberately.

## Example

```bash
python -m backend.market_lab.cross_date_transition_extractor_v1 \
  --audit-json data/historical-evidence/oi-price-regime-audit-2026-08-25-v1-1.json \
  --audit-json data/historical-evidence/oi-price-regime-audit-2026-05-18-v1-1.json \
  --audit-json data/historical-evidence/oi-price-regime-audit-2026-05-12-v1-1.json \
  --rows-csv data/historical-evidence/cross-date-transition-rows-v1.csv \
  --runs-csv data/historical-evidence/cross-date-transition-runs-v1.csv \
  --summary-json data/historical-evidence/cross-date-transition-summary-v1.json
```

Or use an input glob:

```bash
python -m backend.market_lab.cross_date_transition_extractor_v1 \
  --audit-glob 'data/historical-evidence/oi-price-regime-audit-2026-*-v1-1.json' \
  --rows-csv data/historical-evidence/cross-date-transition-rows-v1.csv \
  --runs-csv data/historical-evidence/cross-date-transition-runs-v1.csv \
  --summary-json data/historical-evidence/cross-date-transition-summary-v1.json
```

## Research discipline

Do not select dates based on profitability.
Do not tune rules on a single date.
Do not use retrospective evaluation labels as feature inputs.
Do not collapse session PCR, VWAP, and futures OI into the recent option state.
Do not use this artifact to place orders.
