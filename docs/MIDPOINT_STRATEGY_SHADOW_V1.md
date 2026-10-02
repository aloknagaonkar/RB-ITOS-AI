# Midpoint Strategy — Shadow Live v1

## Purpose

Create a new **Midpoint Strategy** workspace while reusing the existing
Hilega-Milega platform/UI architecture and shared runtime services.

This is **not** a second application.

The intended platform shape is:

```text
Shared market/runtime/UI infrastructure
        |
        +-- Hilega-Milega strategy
        |
        +-- Midpoint Strategy
              +-- Family B   [enabled first]
              +-- Family C   [disabled]
              +-- Family D   [disabled]
              +-- PM/E       [disabled]
```

## Phase M1

Only Family B is active in shadow-live observation.

Safety is frozen:

```text
observation_only=true
execution_enabled=false
paper_order_enabled=false
quantity=None
```

No order placement code belongs in this module.

## Family B management candidate

Entry detection remains the already frozen
`B_DELAYED_FULL_CANDIDATE_A` semantics. Do not rewrite it here.

Management:

1. B reaches +20 proof.
2. At exactly +10 minutes:
   `RUNNER_STRENGTHENING` iff:
   - net directional underlying progress from +20 > 0
   - directional futures-VWAP change > 0
3. Primary exit is OFF.
4. DEGRADED state is owned by the existing frozen deterioration semantics.
5. CAP20 rescue:
   - after degraded-target recovery
   - after >=10 minutes
   - first rebreak below degraded target
   - rescue only when captured directional points <= +20
6. After CAP20 rescue, allow one re-entry:
   - within 20 minutes
   - 1m CLOSE retakes degraded target
   - directional futures-VWAP > rescue-time directional futures-VWAP
7. Maximum one re-entry.
8. No second CAP20 rescue after re-entry.
9. Re-entered leg follows the original structural/session terminal.

## UI

Add a new workspace/navigation section named:

**Midpoint Strategy**

Reuse the same Hilega-Milega presentation patterns/components:

- session status
- live/historical mode
- signal/state summary
- active shadow lifecycle
- option legs
- event timeline
- evidence/journal
- diagnostics
- data health
- historical replay

Midpoint-specific strategy panel should expose at least:

- family
- direction
- opening reference / midpoint / original boundary
- B entry timestamp
- +20 proof timestamp
- classifier timestamp/state
- degraded state/target
- CAP20 state/timestamp
- post-rescue re-entry availability/timestamp
- observation-only safety flags

## Integration boundary

Do not duplicate Hilega infrastructure.

The Midpoint module should feed the existing common runtime/API/UI boundary.
Where the repo already has a common signal/trade DTO, adapt `MidpointSignal`
to that DTO rather than creating parallel transport infrastructure.

## Next integration step

After this additive package passes smoke/tests, wire:

1. frozen canonical Family-B event detector -> `FamilyBShadowRuntime`
2. current 1m underlying + futures-VWAP observations -> manager
3. manager state/signals -> existing journal
4. journal/state -> new `/Midpoint Strategy` workspace using shared UI components

Before editing those files, inspect the actual current API/router/frontend paths
so shared code is reused instead of guessed or copied.
