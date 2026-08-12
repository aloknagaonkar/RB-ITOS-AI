# RB-1.5.2c — Provider-Verified Expiry Recovery

This is a replay/data-fidelity stabilization release. Live trading rules are unchanged.

## Fixed
- Keeps the normal provider expiry-list selection when an expiry on/after the replay date is available.
- When the expiry-list endpoint lags, probes a bounded set of dates on/after the replay date.
- Accepts an inferred expiry only when the provider actually returns expired option contracts for it.
- Never back-selects an expiry before the replay trading date.
- Caches provider-probe contract results so sync does not immediately repeat the same contract request.
- Replay diagnostics show resolution source and provider-probed expiry dates.

## Unchanged
- Primary Decision Engine
- Shadow informational-only policy
- Opportunity Health
- Execution Committee
- Portfolio Risk Manager
- Execution Queue
- Paper Exit Engine

## Validation
- 240 tests passed.
