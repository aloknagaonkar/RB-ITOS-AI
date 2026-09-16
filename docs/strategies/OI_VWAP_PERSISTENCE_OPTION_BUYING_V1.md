# OI_VWAP_PERSISTENCE_OPTION_BUYING_V1

Status: **CANDIDATE_FOR_PAPER_TRADING_IMPLEMENTATION**

Live trading: **DISABLED**

Paper trading: **requires manual enable/approval**

## Purpose

Prospective paper strategy derived from OI/PCR transition + causal futures VWAP context.

The strategy does not use retrospective day classification at runtime.

## Entry lifecycle

### Bullish / CE

1. Fresh bullish P1:
   - previous 5m imbalance <= 0
   - current 5m imbalance > 0
   - PCR 5m change > 0
   - session imbalance improved vs previous checkpoint
2. Last fully completed futures 5m candle available at P1 is ABOVE session VWAP.
3. Wait for next completed OI checkpoint.
4. P2 must remain bullish:
   - current 5m imbalance > 0
   - PCR 5m change > 0
5. Determine exact ATM at P2/execution decision time.
6. Exact ATM CE quote must exist.
7. If open paper positions < 4, emit `ENTER_CE_PAPER`.

### Bearish / PE

Mirror:
- previous imbalance >= 0
- current imbalance < 0
- PCR 5m change < 0
- session imbalance weakens
- completed futures candle BELOW VWAP
- next checkpoint P2 remains bearish
- exact ATM PE
- capacity < 4

## Explicit exclusions

- No absolute 3M OI threshold.
- No VWAP slope requirement.
- No absolute PCR-level threshold.
- No nearest-strike fallback.
- No look-ahead P3/P4 at entry.
- No time-based maximum holding period.
- No live order placement.
- No automatic eviction of an existing position to make room.
- No martingale / averaging / loss-based quantity increase.

## Capacity

`max_open_positions = 4`

Every open position owns independent premium risk state.

## Exit policy for initial paper implementation

Deterministic premium risk layer:
- hard stop: -5%
- breakeven armed after +5%
- trailing armed after +10%
- trailing distance: 3%
- no maximum holding-time exit

This exit policy is kept separate from the entry thesis so it can be replaced later.

## P3 / P4

P3 and P4 are post-entry observational quality fields only in V1.
They MUST be null/unknown at entry time and may be recorded later for research.

## Safety

Data stale, missing OI checkpoint, missing causal VWAP, missing exact ATM instrument,
or missing exact ATM quote => `NO_TRADE` / `DATA_REJECTED`.

Live execution remains disabled.
