# RB-0.7.4.3 Historical Backfill Manager

This release adds historical Upstox Plus options-data backfill under
Intelligence → Maintenance / Backfill.

## What is backfilled

For each historical trading-day candidate:
- applicable option expiry
- spot closing price
- total Call OI
- total Put OI
- OI PCR
- total Call Change-in-OI
- total Put Change-in-OI
- Change-in-OI ratio
- Call Wall
- Put Wall
- derived Max Pain
- strike count
- raw historical OI JSON artifact
- raw historical Change-in-OI JSON artifact

Storage table:

`historical_option_backfill`

Artifacts:

`artifacts/red_bar/options/historical_backfill/<instrument>/<date>/`

## Historical safety rule

Historical OI/Change-in-OI from the Upstox historical endpoints is EOD
research context. It is explicitly stored with:

`entry_aligned = 0`

It does NOT satisfy HYBRID entry-time eligibility and does not replace a real
pre-entry option-chain snapshot captured by the online collector.

This prevents look-ahead leakage.

## Date and expiry handling

The manager:
- combines Upstox historical and active expiry lists when available
- chooses the first expiry on or after each requested trading day
- skips weekends
- continues past no-data/API failures so one holiday does not stop a range
- skips an already backfilled day unless overwrite is enabled
- limits a single run to 186 calendar days

The default UI range is the previous 30 calendar days.

## Change-in-OI

Change-in-OI is requested independently from base OI. If Change-in-OI fails
for a date while base OI succeeds, the OI record is still retained and the
warning is surfaced in the UI.

## UI

Under Intelligence → Maintenance / Backfill:

- Historical Options From
- Historical Options To
- Change-in-OI interval
- Overwrite existing rows
- Backfill Historical Options Data
- Historical Options EOD Context table
- expandable warnings/errors

## Upstox Plus APIs used

- Get Expiries / Expired Expiries
- Historical OI: `/v2/market/oi`
- Historical Change in OI: `/v2/market/change-oi`

## Interaction with the automatic pipeline

The automatic live pipeline remains unchanged:
- online collector = entry/pre-entry options history
- signal-triggered fallback = immediate options capture
- offline/EOD collector = current-session close snapshot
- historical backfill = research/EOD enrichment for older dates

The four paths are independent and do not block each other.

Next planned release:
RB-0.7.5 — Options Intelligence.
