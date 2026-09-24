# Hilega Directional Combined UI — Phase 6 v1

Read-only presentation/API layer for the already-active
`HILEGA_DIRECTIONAL_SHADOW_V1` worker.

## Adds
- `/api/live-shadow/hilega-directional/status`
- `/api/live-shadow/hilega-directional/events`
- `/api/live-shadow/hilega-directional/trade-dashboard`
- Combined UI in the existing **Hilega shadow** tab:
  - exclusive trade owner
  - bullish and bearish state
  - latest accepted/suppressed directional events
  - active CE or PE ATM±2 lifecycle
  - combined exited/non-active CE+PE ledger
  - coordinator activity table

## Safety
No strategy rules are changed. No selection is introduced. No quantity, rupee
P&L, paper orders, or execution. The UI gets direction from the coordinator
audit and never infers it.

The dashboard intentionally does not fabricate option lifecycles that are not
present in the directional audit. Mid-session bootstrap can restore the current
active lifecycle via its audited UPDATE payload, but earlier exited trades from
before directional activation are not invented.

## Validation performed while building this artifact
- new projector tests: 3 passed
- new Python modules: py_compile PASS
- replacement TSX: TypeScript check PASS using local React type stubs

Run the repository's existing directional regression suite on the VM after
installation.
