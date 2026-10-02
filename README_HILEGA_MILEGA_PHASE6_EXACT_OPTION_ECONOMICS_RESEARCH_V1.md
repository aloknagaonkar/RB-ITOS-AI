# Hilega-Milega Phase 6 — Exact Option Economics Research V1

Phase 6 is offline/descriptive research only. It does not change Hilega-Milega signal logic, does not select a contract, does not size quantity, and does not create paper/live orders.

## Purpose

For each exact CE candidate from the frozen ATM±2 candidate set, measure causal forward option economics using exact 1-minute option candles.

For a 5-minute signal bar labelled `10:15`, the strategy decision is known at `10:20`. The research entry is the exact OPEN of the `10:20` option minute. This deliberately differs from Phase 5, which observes the final completed pre-decision minute (`10:19`) for market-state inspection.

Default descriptive horizons are +1, +3, +5, +10 and +15 minutes. For each candidate/horizon the research records close-to-entry return, MFE from exact minute highs, and MAE from exact minute lows.

## Causality / fail-closed rules

- exact contract identity only
- exact decision-boundary 1-minute OPEN for entry
- every minute through the requested horizon must be present
- no nearest-minute fallback
- no interpolation
- no later-contract substitution
- no synthetic premiums
- no retrospective contract switching

If any required exact minute is missing or unhealthy, that candidate is `INCOMPLETE`; the research set is `INCOMPLETE`.

## Deliberately not implemented

- winner/best-contract field
- contract ranking or automatic selection
- premium target
- quantity/risk sizing
- stop/target/trailing rules
- paper/live order creation

The output is intended to provide evidence for a later contract-selection rule, not to create the rule itself.

## Live monitoring remains independent

Keep the Phase 5 shadow worker running while Phase 6 research is developed/tested. Pending live checks remain: fresh Phase 5 option snapshot, natural Route B event, and exact 14:55 cutoff.
