# Hilega Sandbox Event Bridge V1

This phase converts genuine accepted Hilega directional audit events into observation-only broker intents.

## Inputs

- Hash-chain-verified `hilega-directional-v1/step-audit.jsonl`.
- Only `accepted_events` from processed `DIRECTIONAL_DECISION` and `DIRECTIONAL_SESSION_CUTOFF` rows.
- Suppressed, failed and unrelated events are ignored.

## Output

Each recognized event creates a durable `WOULD_SUBMIT` or `WOULD_NOT_SUBMIT` row containing the immutable source hash, event identity, trade identity, direction, CE/PE mapping, BUY/SELL action and one-dynamic-lot policy.

## Safety

- Disabled unless `HILEGA_SANDBOX_BRIDGE_OBSERVATION_ENABLED=1`.
- Does not import or call the Upstox transport.
- Sends neither sandbox nor live orders.
- Verifies the source hash chain before processing.
- Deduplicates using the source record hash and accepted strategy event.
- Reconstructs its active trade state from the durable intent journal after restart.
- Fails closed on ambiguous multiple execution events.
- An exit without a previously observed entry becomes `WOULD_NOT_SUBMIT`.

The bridge must be compared against live Hilega inspection details before it is allowed to call the manually validated sandbox execution adapter.
