# RB-1.3.0 — Candidate Lifecycle + Market Session Manager

## What changed
- Candidates are living entities: NEW → VALID → AGING → EXPIRED / EXECUTED.
- Signals move to AGING after the normal freshness window so Opportunity Extension remains available, but are hard-retired after the lifecycle hard-expiry window (default 5× freshness, 15 minutes at 180s).
- Market-session transitions invalidate old candidates.
- Full VWAP + EMA + momentum loss after the opening minute is treated as confirmed market drift and retires the candidate.
- Duplicate state is explicit and directs the UI to manage the existing position instead of opening another.
- Expired queue rows are moved to EXPIRED.
- Replacement signals are never fabricated: a newer confirmed Red Bar is linked when available, otherwise action is AWAIT_NEW_RED_BAR.
- Candidate lifecycle state/health/session/drift/reason/action is persisted and displayed in Paper Trading.

## Architecture
Red Bar detector → Candidate Lifecycle Manager → Primary Rule Engine → Shadow Advisor → Execution Committee → Queue → Paper Monitor / Exit Engine.
