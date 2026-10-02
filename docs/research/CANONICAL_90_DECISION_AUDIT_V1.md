# Canonical 90 Decision Audit V1

Runs the enriched 90-session population through the frozen causal decision chain:

- exact 5m / 10m / 15m same-strike imbalance + PCR-change classification;
- BULLISH_ALL_3 / BEARISH_ALL_3 / MIXED / INCOMPLETE;
- new opposite directional ALL_3 => C1;
- exact +5m C2 persistence;
- exact C2 futures confirmation;
- explicit PASS / FAIL / INCOMPLETE audit ledger;
- TRADE_ELIGIBLE / TRADE_NOT_TAKEN / INCOMPLETE.

Bullish futures confirmation: LONG_BUILDUP or SHORT_COVERING.
Bearish futures confirmation: SHORT_BUILDUP or LONG_UNWINDING.

No option execution is performed in V1. No forward return or retrospective label is used.
No nearest-time fallback is allowed.

Outputs:
`data/historical-evidence/canonical-decision-audit-v1/<date>.json`
`all-events.csv`
`summary.json`
