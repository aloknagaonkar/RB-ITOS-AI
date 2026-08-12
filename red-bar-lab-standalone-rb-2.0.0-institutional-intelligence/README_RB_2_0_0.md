# RB-2.0.0 — Institutional Intelligence Sprint 1

## Scope
- OI Behaviour Classification: LONG_BUILDUP, SHORT_BUILDUP, SHORT_COVERING, LONG_UNWINDING, NEUTRAL/UNKNOWN.
- Institutional Writing/Buying Detector: CALL_WRITING, PUT_WRITING, CALL_BUYING, PUT_BUYING plus unwind/cover labels.
- Intelligence dashboard using two latest ONLINE option-chain snapshots.
- Bullish/bearish aggregate flow, dominant activity and strongest strike views.

## Safety
- Observation/shadow mode only.
- Execution impact is always NONE.
- No changes to Primary Decision Engine, Shadow execution authority, Opportunity Health, Committee, Portfolio Manager, Queue, position sizing or Exit Engine.

## Data requirement
At least two persisted ONLINE option-chain snapshots with readable chain artifacts and overlapping strikes.
