# Hilega Directional Live Shadow v1

Observation-only live integration for the already validated directional coordinator.

## Invariants

- Frozen bullish engine is unchanged.
- Candidate bearish engine rules are unchanged.
- `HilegaDirectionalCoordinatorV1` is the sole entry arbitration authority.
- ACTIVE ownership is exclusive.
- Opposite ARMED state may coexist informationally.
- Suppressed entries never start option shadow state.
- No same-candle reversal.
- Bullish accepted entry -> five CE ATM±2 shadow legs.
- Bearish accepted entry -> five PE ATM±2 shadow legs.
- Exact 1m OPEN entry/exit semantics are retained by the existing lifecycle engines.
- No nearest-minute or nearest-strike fallback.
- No option selector, quantity, rupee P&L, paper order, or real order.

## Live strategy selector

Set:

`LIVE_SHADOW_STRATEGY=HILEGA_DIRECTIONAL_SHADOW_V1`

Keep `HILEGA_MILEGA_OPTION_EXPIRY` configured to the intended active expiry.

## Audit paths

- `data/live-observation/hilega-directional-v1/step-audit.jsonl`
- `data/live-observation/hilega-directional-v1/data-health.jsonl`

The previous bullish-only audit remains separate and untouched.

## Activation

Installation requires no restart. Activation does require an intentional restart of only the Hilega live-shadow worker because the selected live strategy is read at process startup. Do not restart the API or main market worker for this change.
