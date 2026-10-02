# P3H.5 Canonical 90-Session Replay V1

This phase runs the frozen P3H.4.1 causal replay across the canonical
development population only.

## Governance

Population:
- TRAIN
- OOS_A
- OOS_B
- OOS_C
- OOS_D

Window:
- 2026-05-04 through 2026-09-08

Expected:
- exactly 90 sessions

Excluded:
- OOS_E
- OOS_F
- OOS_G
- OOS_H

The CLI hard-fails if the discovered intersection is not exactly 90 sessions.
It will not silently substitute another population.

## Required data per session

A session must exist in all three:
1. historical positioning cache
2. historical option OHLC cache
3. futures development CSV

## Execution model

Frozen P3H.4.1:
- P2 causal confirmation
- exact ATM CE/PE
- next-minute option OPEN proxy entry
- -5% hard stop
- +5% breakeven activation
- +10% trailing activation
- 3% trailing distance
- raised stop activates next minute
- gap-through active stop fills at OPEN
- intrabar active stop touch fills at stop

Historical bid/ask remains unavailable, so this is not production-fill parity.

## Metrics

The report includes:
- signals, entries, rejects
- winners, losers, breakeven
- win rates
- median trade return
- additive aggregate trade return
- additive sequential trade drawdown diagnostic
- bullish/bearish split
- exit reason split
- per-session results

The drawdown metric is intentionally labeled a diagnostic. It is not
capital-weighted portfolio drawdown because quantity/capital allocation has not
yet been modeled.
