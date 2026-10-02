# FULL_SHADOW_INTEGRATION_REPLAY_V1

## Purpose

Exercise the entire observational pipeline deterministically before any live production wiring.

Flow:

1. raw `Snapshot`
2. data health
3. normalized moving-ATM +/-5 OI features
4. 5m/10m/15m ALL_3
5. new opposite ALL_3 detection
6. candle-2 survival
7. exact futures 5m OI state
8. futures alignment
9. SPOT_LAG / SPOT_ALREADY_MOVED classification
10. exact ATM option instrument
11. exact next-minute hypothetical option entry
12. strict contiguous option 1m candles
13. stop / BE / trail / time exit
14. CLOSED or INCOMPLETE
15. hash-chained audit log

No broker execution is present.

## Acceptance criteria

The end-to-end test must prove:

- one observation can move from DETECTED to CLOSED;
- exact futures state is matched at the same C2 timestamp;
- exact ATM instrument is used;
- exact next-minute entry is used;
- 1-minute option continuity is enforced;
- missing option minute fails closed;
- exit P&L is deterministic;
- audit hash chain verifies after replay.

## What this does not yet prove

This is an integration contract/replay test. It does not prove that production Upstox/live adapters
already supply every required futures and option-minute field. That is the next production-wiring step.
