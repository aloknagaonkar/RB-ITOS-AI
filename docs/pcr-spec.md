# PCR calculation specification v1

Engine: `pcr-1.0.0`. All decisions below are explicit research rules; default values are not optimized trading parameters.

## Formula and scope

For one underlying, one explicit expiry and a selected set of strikes:

`OI PCR = sum(put OI across selected strikes) / sum(call OI across selected strikes)`

For every CE and PE contract, retain Upstox `oi` and `prev_oi`. Report:

- `change OI = oi - prev_oi`
- `change % = change OI / prev_oi * 100`

Each Fixed, Moving and Full Chain section has its own strike table and totals. Panel percentage change is calculated from summed OI and summed previous OI; strike percentages are never averaged. A zero or unavailable previous OI produces an unavailable percentage.

Never average per-strike PCR values. Zero total call OI produces an unavailable ratio. Zero put OI with a positive call total is a valid zero. Missing, fractional, negative, boolean or malformed Upstox OI is unavailable, never silently zero. OI is supplied by the provider; the application computes aggregation and PCR, not exchange-wide OI from trades. Change-in-OI PCR is a separate future indicator.

## ATM and range selection

- Use the separately fetched underlying spot quote.
- Select the nearest strike from the independently fetched contract catalog. At an exact midpoint choose the lower strike.
- Select N available listed strikes below and N above ATM, plus ATM itself. Default N=5 is editable. N=0 selects ATM only.
- Require the full requested number of strikes and both sides at each strike. A range near the catalog boundary is unavailable instead of silently narrowed.
- Select contracts using catalog identity, not whichever quotes happened to arrive. Missing quotes cannot shift ATM or redefine expected coverage.
- Pin an explicit expiry; there is no automatic expiry rollover in v1. Persist catalog and expiry with every observation.

## Fixed morning ATM

Default anchor is 09:20 IST with a 120-second inclusive tolerance. Capture the first observation received at/after that time and within tolerance, with acceptable underlying quote timestamp, collection duration and catalog range. OI availability does not determine the spot-based anchor; missing OI still makes that observation's affected PCR unavailable.

Save capture time, session date, provider, underlying, expiry, spot, ATM and exact contract keys. Keep these contracts throughout that session even when the underlying moves. Recover the anchor from the previous committed observation after restart. If the window passes without capture, fixed mode is missed for the session; do not silently capture at startup later in the day. A new session or configuration version requires a new anchor.

The source quote timestamp is feed-level evidence only. v1 cannot prove a per-field spot refresh or an exchange-time morning anchor. This limitation is visible in evaluation warnings.

## Moving ATM

Recompute ATM and the selected range at each observation, using the same spot and snapshot as fixed mode. Record exact contract keys and mark range changes on the chart. PCR movements may arise from OI changes or membership changes. Chart markers identify membership shifts but do not yet quantify their separate contributions.

Full-chain mode aggregates all paired catalog strikes in the same expiry as a research reference.

## Validity and freshness

- Default observation interval: 60 seconds; configurable 15–3600 seconds. Sequential REST requests are not an atomic exchange snapshot.
- Default maximum collection duration: 20 seconds. Slower observations are recorded with unavailable PCR.
- Default underlying feed age: 30 seconds at receipt. Missing timestamps, stale timestamps and timestamps more than two seconds ahead block calculation/anchor capture.
- Regular session gate: weekdays 09:15 inclusive to 15:30 exclusive, IST. Exchange holidays and special sessions remain an explicit limitation.
- Expected/received contract counts and missing OI are checked separately for each mode. Missing contracts outside a local range can invalidate full-chain PCR while that local range remains valid.
- Upstox chain OI has no dedicated source timestamp in the documented schema. Record null and warn. Research PCR may still be displayed, but entry eligibility always remains false in this release.
- Unchanged values are not considered stale solely because they are unchanged.
- Reception/commit age and worker heartbeat are wall-clock operational measures, distinct from source-data freshness. Synthetic data uses a clearly labelled simulated market clock.

## Replay

Read observations in commit order for one configuration. Reconstruct anchors from inputs using the same pure calculation function and recorded observation times; do not consult current market data or the replay machine's clock. Compare complete evaluation payloads, including engine version, warnings, contract sets and anchor provenance. Report mismatching observation IDs. No records is not a successful replay. Changed engine behavior must get a new version; legacy calculation versions will need registered implementations as versions accumulate.

## Acceptance evidence

Tests cover sum-based aggregation, fixed/moving divergence, midpoint selection, missing OI, zero denominator, quote staleness/unknown/future timestamps, collection delays, anchor window boundaries, missed capture, daily reset, catalog truncation/duplicates, expired/out-of-session observations, persisted restart recovery, out-of-order rejection, tampered result detection, API configuration isolation and sanitized provider failures.
