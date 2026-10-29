# Hilega risk-evidence audit v1

This is a read-only source-availability bridge toward risk integration. It inspects persisted application and adapter references; it does not authenticate current fills/P&L, produce entry permission, open broker transport, or install risk enforcement. Existing no-history data cannot establish verified zero strategy P&L.

## Validate

Extract into `~/RB-ITOS-AI/hilega-risk-evidence-audit-tools-v1`. Run `python -W error::ResourceWarning -m unittest discover -s hilega-risk-evidence-audit-tools-v1 -p 'test_*.py' -v` with the repository virtualenv. Then run `risk_evidence_audit.py check` with that Python. The CLI defaults to `~/RB-ITOS-AI` and the existing private account-pin file. It needs no token and performs no broker GET or mutation.

An ordinary completed audit returns `BLOCKED_EVIDENCE_GAPS`. That is expected: current signed account/fill/fee evidence and live P&L are not assessed by this contract. A process exit of zero means the audit ran, NOT that trading is cleared. Schema, scope, version, reference-integrity or control-state failures exit nonzero with a bounded diagnostic. Do not edit source data/hashes to force the audit through.

## Checked references

- Persisted PREPARATION_ONLY route and PAUSED control; pinned adapter account scope and LIVE_CLOSED mode.
- Plan/hold/outbox record identities; atomic-binding digests; immutable request and disabled-draft fingerprints; contract, hold and evidence hash consistency.
- Existing receipt review semantics: exactly one PLACE attempt, matching wire/provenance, durable successful receipt, single order acknowledgement bound to the request. Acknowledgement is not a fill.
- Orphan attempts/receipts, unbound requests, missing bindings and simulator history are reported or rejected without adopting orders.

The pure historical receipt checker and order-ack parser are extracted verbatim from the existing reviewed repository functions. This package deliberately does not construct their Store class because its constructor opens a write transaction and initializes metadata. CLI checks pin the installed receipt/mapping versions. Local hash consistency is not signature verification, live ownership or proof that the local hold reserved broker cash.

## Read-only boundary

Both databases are opened with SQLite URI `mode=ro`, the adapter is attached read-only, and `query_only=ON` plus one read transaction covers source collection. Database header versions are checked before SQLite open to reject WAL mode without creating recovery sidecars; no journal conversion is attempted. Source symlinks, identical database files, non-paused controllers and mismatched scopes/modes are rejected. Tests verify source bytes unchanged and no new sidecars for the covered cases. No production SQLite file is copied, replaced, restored or initialized.

Output contains counts and evidence gaps, never raw pin keys/tokens/account IDs, request bodies or receipt bodies. `--report` optionally writes one fresh 0600 JSON file directly under the repository research directory; existing destinations cannot be overwritten.

## Deliberately pending

The signed account snapshot format contains normalized trade quantities/prices but not a complete strategy-owned net P&L/fee ledger. Receipt review explicitly retains ownership=false. The bridge therefore always leaves net P&L unavailable, fee completeness/ownership false, and production readiness false. It does not infer ownership from an instrument or tag, infer complete fees from a caller boolean, adopt simulation fills, or treat empty tables as authenticated zero P&L.

Next integration requires an authenticated ownership/fill evidence contract, complete fees and approved marking/accounting policy, durable daily-stop state, approved account risk limits, and atomic enforcement beside reservations at the execution boundary. The existing fresh-signal admission milestone, production submission, exits, reconciliation and pilot gates remain pending.

This package changes no application source, controller, .env, reservation or service. Do not restart services to run it. Keep PAUSED. Do not share private database/pin/evidence files; the printed summary is sufficient.
