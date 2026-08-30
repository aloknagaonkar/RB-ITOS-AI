# Trade Evidence & Market Readiness: Validation and Change Plan

## Purpose

This document records the code validation findings and the changes required to improve the **Trade Evidence & Market Readiness** page. It is a planning document only. The recommendations do not grant this page execution authority.

## Current implementation

The page currently combines the latest available records from these sources:

- Global market-readiness snapshots
- Red Bar V2 signal diagnostics
- NIFTY futures diagnostic snapshots
- Option-context snapshots
- ATM-window option-participation snapshots
- Ranked option-candidate snapshots

The independent market view uses option-participation scores as its primary direction and futures positioning as confirmation or contradiction. Red Bar V2 is displayed separately and both views are compared for alignment.

The runtime option capture selects the point-in-time nearest ATM strike, detects the strike interval, and collects ATM plus four strike steps on each side for both CE and PE. This produces up to nine CE and nine PE observations.

## Important interpretation

The present result is a deterministic evidence score. It is not a calibrated probability of profit. Labels such as `STRONG`, `MODERATE`, and `CAUTIOUS` describe rule-based evidence strength and must not be presented as measured prediction accuracy until historical calibration is implemented.

## Validated issues and required changes

### P0: Align all evidence to one timestamp

**Current issue:** Each source is loaded using its independently latest row. This can combine option, futures, readiness, signal, and candidate observations from different times.

**Required changes:**

1. Establish a page-level `as_of_timestamp` or `evidence_bundle_id`.
2. Resolve every input at or before that timestamp.
3. Persist source timestamps with the recommendation.
4. Add age and alignment fields for every source.
5. Refuse an actionable grade when mandatory evidence is stale or outside the allowed alignment tolerance.

Suggested freshness policy:

| Evidence | Fresh | Aging | Stale |
|---|---:|---:|---:|
| Spot and option quote | <= 60 sec | 61-120 sec | > 120 sec |
| Option chain and OI | <= 2 min | 2-4 min | > 4 min |
| Futures snapshot | <= 2 min | 2-4 min | > 4 min |
| Strategy signal | Matching closed candle | One candle behind | Older |

Thresholds should be configuration values and validated against observed provider behavior.

### P0: Make the independent path genuinely independent

**Current issue:** The independent recommendation consumes global blocking reasons, while global readiness includes Red Bar V2 alignment. A V2 condition can therefore block the independent path indirectly.

**Required changes:**

Split readiness into:

- `market_data_readiness`
- `independent_strategy_readiness`
- `red_bar_v2_readiness`
- `execution_readiness`

The independent recommendation may consume market-data and independent-strategy readiness only. Red Bar V2 alignment should be applied solely in the comparison/alignment section.

### P0: Correct the UI description of the strike window

**Current issue:** The runtime captures ATM +/- 4 for both CE and PE, but the page describes a six-strike calculation using ATM and two OTM strikes per side.

**Required changes:**

- Rename the section from `Six-Strike Option Participation` to `ATM +/- 4 Option Participation`.
- State that the same nine strike levels are evaluated for both CE and PE.
- Display strike offset and moneyness: `-4 ... ATM ... +4`, with `ITM`, `ATM`, and `OTM` labels for each option type.
- Display the detected strike interval and number of expected versus available contracts.

### P1: Remove volume double counting

**Current issue:** Volume contributes points inside each strike score, and the full strike score is then volume-weighted during side aggregation.

**Required change:** Use volume once. Recommended design:

- Retain normalized volume acceleration as a score feature.
- Aggregate strike scores using distance, liquidity, and data-quality weights instead of raw volume.

### P1: Normalize OI and volume

**Current issue:** Absolute OI direction is rewarded without sufficient normalization. Small and very large OI changes can receive similar rule points.

**Required calculations:**

```text
oi_change_pct = (current_oi - reference_oi) / max(abs(reference_oi), epsilon)
oi_change_zscore = (oi_change_pct - intraday_mean) / intraday_stddev
volume_acceleration = current_interval_volume / median_same_time_baseline
```

Use both a minimum absolute change and a normalized materiality threshold. Baselines should be segmented by time of day and expiry proximity.

### P1: Apply moneyness-distance weights

Deep ITM, ATM and deep OTM observations have different sensitivity and liquidity. Apply an explicit distance decay, initially:

| Distance from ATM | Weight |
|---|---:|
| ATM | 1.00 |
| +/- 1 | 0.90 |
| +/- 2 | 0.75 |
| +/- 3 | 0.55 |
| +/- 4 | 0.35 |

These values are initial research parameters and must later be calibrated.

### P1: Add contract-liquidity eligibility

Bid, ask and spread are captured but do not currently reduce the prediction or candidate score.

Required calculation:

```text
midpoint = (bid + ask) / 2
spread_pct = (ask - bid) / midpoint * 100
```

Initial policy for validation:

| Spread | Treatment |
|---|---|
| <= 1% | Eligible |
| > 1% and <= 2% | Small penalty |
| > 2% and <= 3% | Large penalty |
| > 3% | Reject |
| Missing/invalid quote | Unavailable, not eligible |

Also require minimum volume, minimum OI, valid lot size, positive premium, and valid expiry.

### P1: Use IV as option-buying risk evidence

IV is displayed but not used in the current recommendation.

Required additions:

- Calculate IV percentile using point-in-time historical observations.
- Penalize extremely elevated IV for new option buying.
- Measure short-term IV direction and CE/PE skew.
- Flag a possible IV-crush risk even when the underlying direction is correct.

IV should affect contract quality more strongly than underlying direction.

### P1: Use PCR behavior, not only availability

PCR availability is currently treated as positive evidence without using its directional meaning.

Required additions:

- PCR OI level
- PCR OI change
- Intraday PCR slope
- Attribution of the change to call addition/unwinding and put addition/unwinding

PCR should remain confirmation or contradiction evidence, not a standalone entry trigger.

### P1: Implement the complete frozen RSI reversal evidence

Displaying RSI or awarding static RSI points is not equivalent to the frozen reversal strategy.

Persist and display each state independently:

```text
Extreme reached
-> Cross-back completed
-> Confirmation candle direction valid
-> Structure reclaimed/lost
-> Adverse extreme absent
-> RSI reversal eligible
```

The state must use closed candles, record the exact 15-minute signal candle, and prevent look-ahead. Lower-timeframe option data may confirm contract quality but must not rewrite the 15-minute reversal signal.

### P1: Improve candidate ranking

The three highest strike scores are currently selected without genuinely different role policies.

Required role definitions:

- `PRIMARY`: best combined directional, liquidity, delta and spread score.
- `SAFER`: stronger liquidity, tighter spread and higher absolute delta.
- `AGGRESSIVE`: lower premium and lower delta, allowed only with strong evidence and adequate liquidity.

For the agreed two-entry RSI policy, return exactly the best two independently eligible contracts. Do not duplicate one contract under two role names.

### P2: Separate readiness replay from prediction performance

The current replay shows operational readiness counts, not trading accuracy.

Add a separate outcome-calibration dataset containing:

- Recommendation timestamp and evidence bundle
- Suggested side and selected contract
- Entry quote and estimated slippage
- Whether +5% was reached before -3%
- Whether +8% and +12% were reached
- Maximum favorable excursion
- Maximum adverse excursion
- Exit result under the frozen trailing policy
- Net return after estimated fees and slippage

Report results by strategy, market regime, time bucket, expiry distance, evidence grade and candidate role.

## Recommended calculation pipeline

```text
1. Evidence bundle and timestamp alignment
   -> freshness, expiry, completeness, no-look-ahead

2. Underlying directional hypothesis
   -> strategy-specific signal, structure and market regime

3. Derivatives confirmation
   -> normalized OI flow, volume acceleration, PCR behavior, futures state

4. Contract eligibility and quality
   -> moneyness, delta, IV, bid/ask spread, volume and OI

5. Conflict resolution
   -> supporting, contradictory and unavailable evidence kept separate

6. Historically calibrated outcome estimate
   -> probability, expected value and uncertainty for a defined exit policy
```

## Proposed score structure before calibration

Do not simply add correlated observations multiple times. A provisional normalized score may use groups:

| Group | Maximum contribution |
|---|---:|
| Strategy direction and structure | 30 |
| Option OI and premium behavior | 25 |
| Futures and PCR confirmation | 15 |
| Volume acceleration | 10 |
| Contract quality: spread/delta/IV | 15 |
| Data freshness and completeness | 5 |

Contradictory evidence should subtract points. Missing evidence should reduce completeness/confidence rather than silently contribute zero as if it were bearish or low quality.

## Required UI outputs

The page should expose the reasoning in normal language and live values:

| UI field | Meaning |
|---|---|
| Evidence as of | Common timestamp used for the calculation |
| Source freshness | Age and state for every input |
| Direction | Bullish, bearish, neutral, or conflicted |
| Suggested trade | CE, PE, or wait |
| Strategy evidence | Exact strategy states that passed or failed |
| Option confirmation | OI, volume, PCR and futures support/conflict |
| Contract eligibility | Why each candidate passed or failed |
| Main supporting evidence | Strongest non-duplicated reasons |
| Main risk | Strongest contradictory or execution-quality risk |
| Confidence type | Heuristic until calibrated; probability after calibration |
| Authority | Always display observational/execution authority explicitly |

Each displayed metric should provide an expander with:

- Raw live value
- Formula or threshold used
- Passed/failed/unavailable state
- Source timestamp
- Human-readable explanation

## Other required corrections

1. Filter the latest option-context query by underlying/instrument and expiry.
2. Do not hide the complete page when global readiness is missing; render other available sections and mark the missing section unavailable.
3. Validate that candidate, participation and recommendation timestamps belong to the same evidence bundle.
4. Persist policy version and threshold version with every recommendation.
5. Preserve `OBSERVATIONAL_ONLY` until the model has completed point-in-time backtesting, paper observation and approval.

## Implementation order

1. Timestamp-aligned evidence bundle and freshness policy.
2. Independent readiness isolation from Red Bar V2.
3. ATM +/- 4 UI correction and moneyness visibility.
4. Liquidity eligibility and spread penalty.
5. OI/volume normalization and removal of double counting.
6. IV and PCR confirmation calculations.
7. Frozen RSI state telemetry.
8. Two-contract role-based candidate selection.
9. Outcome labeling and walk-forward calibration.
10. Replace heuristic confidence language only when calibration evidence exists.

## Acceptance criteria

- Every recommendation can be reproduced from one persisted evidence bundle.
- No future observation is used in a historical decision.
- Independent strategy readiness does not consume Red Bar V2 state.
- The UI accurately states ATM +/- 4 CE and PE coverage.
- Stale or misaligned mandatory evidence cannot produce an actionable grade.
- Missing evidence is shown explicitly.
- Illiquid contracts cannot rank as eligible candidates.
- Score components are individually visible and do not double-count volume.
- RSI reversal status reflects the complete frozen sequence.
- Any displayed probability is backed by out-of-sample option outcome calibration.
- The page remains non-authoritative until separately approved for execution use.

## Operations Centre: Data Readiness Gate v1 validation

### Scope and conclusion

Data Readiness Gate v1 is correctly isolated as a read-only diagnostic layer. It currently observes market-context enrichment, volume/structure enrichment, option-context linkage, CORE/HYBRID eligibility and option-collector freshness. It does not currently validate the Red Bar V2 `NEXT_RED_CANDLE` reference, reference midpoint, or complete strategy-context alignment. It therefore does not resolve or fully explain Section 4 `REFERENCE_NOT_READY` by itself.

### Current pipeline calculations

For the readiness-scoped confirmed signal IDs:

```text
missing market  = confirmed signal IDs - market-context signal IDs
missing volume  = confirmed signal IDs - volume-structure signal IDs
missing options = confirmed signal IDs - entry-aligned option-context signal IDs

CORE   = market context AND volume structure
HYBRID = CORE AND entry-aligned option context
```

When any current Red Bar V2 signal IDs exist, the service scopes the readiness calculation to IDs beginning with `RBV2-`. This prevents current V2 readiness from being mixed with legacy-only signals.

The observed `28 confirmed / 0 market / 0 volume / 27 options / 0 CORE / 0 HYBRID` state is internally consistent:

- All 28 confirmed V2 IDs lack matching market-context rows.
- All 28 confirmed V2 IDs lack matching volume-structure rows.
- Twenty-seven IDs have option context explicitly marked `entry_aligned`.
- One ID lacks aligned option context.
- CORE is zero because both market and volume are mandatory.
- HYBRID is zero because HYBRID requires CORE first.

### Likely cause of all market and volume enrichment being absent

The market and volume enrichment services use the historical 1-minute candle repository. Each service first requires the signal's trading date to exist in `historical.available_dates(...)`. When the current live session has not been written into that historical repository, current-day signals are skipped even though live signals and option snapshots exist.

Required architectural correction:

- Define a point-in-time candle source interface shared by live and historical enrichment.
- In a live session, use persisted completed live candles up to the signal timestamp.
- In replay, use historical candles only up to the same timestamp.
- Persist the selected source, latest candle timestamp and no-look-ahead cutoff.
- Never silently skip a signal because the preferred repository lacks the date.

### Confirmed strengths

1. Readiness is calculated using signal-ID membership rather than comparing row counts only.
2. Red Bar V2 is preferred as the readiness scope when V2 signals exist.
3. Options become prediction features only when `entry_aligned` is true.
4. Option alignment requires the option snapshot to be at or after confirmation and within the configured 120-second window.
5. CORE and HYBRID eligibility are calculated per signal in the pipeline orchestrator.
6. The gate has no execution authority and does not mutate frozen strategy decisions.

### P0: Add Red Bar V2 reference readiness

Add a dedicated stage before market enrichment:

```text
Confirmed Red Bar V2 signal
-> NEXT_RED_CANDLE reference exists
-> Reference data quality is VALID
-> Reference high, low and midpoint are populated
-> Reference timestamp precedes the signal confirmation timestamp
-> Strategy reference READY
```

Required fields:

| Field | Validation |
|---|---|
| Reference type | Must be `NEXT_RED_CANDLE` |
| Reference timestamp | Present and not later than confirmation |
| Reference high | Numeric and finite |
| Reference low | Numeric and finite |
| Reference midpoint | Numeric, finite and between high/low |
| Data quality | `VALID` |
| Failure reason | Explicit code and human-readable explanation |

The Section 4 live resolver must query `NEXT_RED_CANDLE`, not `FIRST_CANDLE`. The reference type should be owned by the strategy policy and reused by diagnostic readers rather than duplicated as unrelated string constants.

### P0: Replace hardcoded availability cards

The following card values are currently labels rather than validated data coverage:

- 1-minute OHLC `Supported`
- RSI(7) input `Supported`
- Spot/ATM `Available`
- CE/PE price `Available`
- Volume/OI/PCR `Available`
- Bid/Ask `Available`
- IV and Greeks `Available`

Calculate availability from persisted field coverage instead:

| Input | Required diagnostic |
|---|---|
| 1-minute OHLC | Completed rows available up to the signal timestamp |
| Candle freshness | Latest completed candle age and expected candle timestamp |
| Volume | Non-null/non-negative coverage and current/baseline availability |
| RSI | Exact RSI period, timeframe, value and source timestamp |
| Spot/ATM | Point-in-time spot and detected ATM available |
| CE/PE premium | Valid premium count / expected contract count |
| OI and volume | Valid count, zero count and stale count |
| Bid/ask | Valid two-sided quote count and crossed-market count |
| Greeks/IV | Valid count per field and provider timestamp |

Example UI values:

```text
CE/PE premiums: 18/18 valid
Bid/ask: 14/18 valid
OI: 18/18 valid
Volume: 17/18 valid
IV: 16/18 valid
Delta: 16/18 valid
```

### P0: Correct Feature Store readiness calculation

The UI currently estimates complete CORE inputs using:

```text
min(market_ready_count, volume_ready_count)
```

This is not sufficient because the market-ready and volume-ready rows may belong to different signals.

Required calculation:

```text
core_feature_ids   = market_ids INTERSECTION volume_ids
hybrid_feature_ids = core_feature_ids INTERSECTION option_ids

core_feature_count   = count(core_feature_ids)
hybrid_feature_count = count(hybrid_feature_ids)
```

The displayed Feature Store counts should either use these intersections or read the persisted per-signal `core_eligible` and `hybrid_eligible` states.

### P1: Persist per-signal enrichment outcomes

Market and volume services currently skip unavailable dates and catch selected calculation exceptions without persisting a per-signal reason. Add an enrichment outcome record containing:

- Signal ID and strategy ID
- Stage name
- Status: `READY`, `MISSING`, `FAILED`, `STALE` or `NOT_APPLICABLE`
- Error/reason code
- Human-readable reason
- Input source
- Input cutoff timestamp
- Latest source timestamp
- Attempt timestamp
- Retry count and final retry status
- Policy version

Recommended reason codes include:

```text
CURRENT_DAY_CANDLES_UNAVAILABLE
INSUFFICIENT_COMPLETED_CANDLES
SIGNAL_TIMESTAMP_INVALID
MARKET_CONTEXT_CALCULATION_FAILED
VOLUME_COLUMN_UNAVAILABLE
OPTION_SNAPSHOT_OUTSIDE_LINK_WINDOW
OPTION_SNAPSHOT_PRECEDES_SIGNAL
REFERENCE_NOT_FOUND
REFERENCE_DATA_QUALITY_INVALID
```

### P1: Report real pipeline errors

The current Operations Centre error count maps overall pipeline status `PARTIAL` to one error and other states to zero. This is a status indicator, not a true count.

Required changes:

- Persist structured errors by run, signal and stage.
- Count unresolved error records.
- Display total attempts, failed attempts, recovered retries and unresolved failures separately.
- Preserve the overall run status as a separate field.

### P1: Preserve full timestamps for freshness

The latest option snapshot is currently reduced to a time-only display string and later parsed again for age calculation. Keep separate values:

```text
last_snapshot_timestamp = complete timezone-aware ISO timestamp
last_snapshot_display   = formatted local time for the UI
```

Freshness calculations must always use the complete timestamp. The UI should display source timestamp, page timestamp and calculated age.

### P1: Separate collector freshness from signal alignment

`Fresh - 86s` describes the latest collection. It does not prove that every one of the 27 linked signals used a suitably aligned snapshot.

Display these separately:

- Collector freshness: age of latest successfully collected chain.
- Per-signal alignment: snapshot delay relative to signal confirmation.
- Alignment coverage: aligned signals / confirmed signals.
- Delay distribution: minimum, median, p95 and maximum seconds.
- Missing reason: no later snapshot, snapshot too old, or invalid timestamp.

### P1: Make RSI labeling truthful

`RSI(7) input: Supported` is not currently backed by a Data Readiness Gate RSI feature. The market feature store exposes ATR14, EMA9, EMA21, trend and realized-volatility fields but no RSI(7) readiness field.

Required choice:

- Remove the RSI(7) row from this gate; or
- Persist the exact RSI(7) value, timeframe, closed-candle timestamp and readiness state.

Do not use `Supported` as a substitute for `Available now`.

### Required signal drill-down

Add an expander/table that makes the aggregate counts auditable:

| Signal | Reference | Market | Volume | Options | CORE | HYBRID | Main reason |
|---|---|---|---|---|---|---|---|
| RBV2-... | READY/MISSING | READY/MISSING | READY/MISSING | READY/MISSING | YES/NO | YES/NO | Explicit reason |

Selecting a row should show:

- Confirmation timestamp
- Reference timestamp and values
- Market/volume candle cutoff
- Option snapshot timestamp and delay
- Feature fields present/missing
- Policy versions
- Source artifact/database identifiers

### Revised readiness flow

```text
1. Confirmed Red Bar V2 signal
   -> valid signal ID and closed-candle confirmation

2. Strategy reference readiness
   -> valid NEXT_RED_CANDLE high/low/midpoint

3. Market context readiness
   -> point-in-time candle and structure inputs

4. Volume/structure readiness
   -> volume, baseline and structure inputs

5. Option context readiness
   -> entry-aligned ATM-window snapshot

6. Evidence bundle readiness
   -> same signal ID, aligned timestamps and policy versions

7. Feature eligibility
   -> CORE and HYBRID computed per signal

8. Execution readiness
   -> separate authority-owned gate; not part of diagnostic v1
```

### Operations Centre implementation priority

1. Correct the Red Bar V2 reference type and add reference readiness.
2. Replace hardcoded availability labels with persisted coverage checks.
3. Use signal-ID intersections for Feature Store counts.
4. Support live point-in-time candles for current-day market/volume enrichment.
5. Persist per-signal stage outcomes and failure reasons.
6. Separate full timestamps from display strings.
7. Separate collector freshness from per-signal alignment.
8. Add the 28-signal drill-down and explicit missing reasons.
9. Keep the gate read-only until a separately versioned admission policy is approved.

### Additional acceptance criteria for Data Readiness Gate v1

- A valid `NEXT_RED_CANDLE` reference is detected consistently across strategy, runtime and UI.
- Every aggregate count can be reconciled to a list of exact signal IDs.
- Feature Store CORE count equals the market/volume signal-ID intersection.
- Availability cards contain observed coverage, not hardcoded capability labels.
- Every missing enrichment has a persisted reason code.
- Live-session signals can be enriched from completed live candles without look-ahead.
- Full timezone-aware timestamps are retained through freshness calculations.
- Collector freshness and signal alignment are displayed separately.
- RSI readiness names its exact period and timeframe or is not displayed.
- Diagnostic readiness remains isolated from execution authority.
