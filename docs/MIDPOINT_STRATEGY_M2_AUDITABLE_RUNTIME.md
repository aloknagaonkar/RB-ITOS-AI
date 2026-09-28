# Midpoint Strategy — M2 Auditable Family B Runtime

## Scope

M2 extends the already-passed M1 foundation.

M2 adds:

- canonical delayed Family-B detector
- actual structure / boundary / futures-VWAP inputs
- auditable lifecycle wrapper
- rejected-decision evidence
- append-only JSONL journal
- deterministic event IDs
- restart-safe duplicate suppression for deterministic events
- replay/audit validation
- smoke test + unit tests

M2 does **not** yet wire guessed Hilega router/frontend filenames.

## Frozen Family B entry

`B_DELAYED_FULL_CANDIDATE_A`

Requirements:

1. original structural boundary event exists
2. original event does **not** already have full Candidate A
3. maximum delay = 10 minutes
4. same directional structure remains valid
5. price remains beyond the original boundary
6. full Candidate A appears later

Full Candidate A:

Bearish:

```text
current futures - VWAP < -5
AND
some prior value inside T-5..T >= -5
```

Bullish mirror:

```text
current futures - VWAP > +5
AND
some prior value inside T-5..T <= +5
```

## Audit policy

The journal is the source of truth; the future UI is a projection.

Both triggers and meaningful non-triggers are journaled.

Examples:

```text
B_WATCH_STARTED
B_CONFIRMATION_CHECK -> WAIT
B_CONFIRMATION_CHECK -> ENTRY
B_ENTRY
PLUS20_PROOF
RUNNER_CLASSIFICATION
DEGRADED_STARTED
DEGRADED_TARGET_RECOVERED
CAP20_CHECK -> NO_ACTION
CAP20_RESCUE_TRIGGERED
POST_RESCUE_REENTRY_CHECK -> NO_ACTION
POST_CAP20_REENTRY_TRIGGERED
```

Each row includes:

- session / timestamp / strategy version / family
- direction
- state before / after
- raw underlying/futures/VWAP evidence
- reference high / low / midpoint / original boundary
- directional points
- condition booleans
- result / reason
- observation-only safety fields
- `order_sent=false` on shadow action intents

## Safety

Every row must preserve:

```text
observation_only=true
execution_enabled=false
paper_order_enabled=false
quantity=None
```

M2 contains no order-placement integration.

## Next phase

M3 should inspect the exact current Hilega runtime/API/frontend files and wire this
engine into those shared components rather than duplicating infrastructure.

Recommended integration order:

1. current shared 1m underlying feed
2. current futures/VWAP feed
3. current session lifecycle/restart hooks
4. existing journal/evidence storage location
5. common API DTO/router
6. new Midpoint Strategy UI workspace
