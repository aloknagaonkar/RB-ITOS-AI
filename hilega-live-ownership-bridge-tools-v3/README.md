# Live ownership reference bridge v3

Standalone read-only checker. No installation into application runtime.

## What this advances
One assessment now follows application plan/hold/outbox and disabled-request
fingerprints, durable acknowledgement provenance, and a fresh locally signed
pinned-account capture through matching order and trade references.

This is reference linkage, not an ownership ledger or an executable risk gate.
The fixture ownership ledger is neither imported nor modified. No live evidence
is relabelled as a fixture by the CLI.

## Run on the VM
Extract into a fresh directory from the repository root:
    .venv/bin/python -m zipfile -e hilega-live-ownership-bridge-v3.zip hilega-live-ownership-bridge-tools-v3
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-live-ownership-bridge-tools-v3 -p 'test_*.py' -v
    PYTHONPATH=backend:. .venv/bin/python hilega-live-ownership-bridge-tools-v3/bridge.py check --capture-account

Optional --repo and --pin-file select the repository and existing private account
pin. Never pass a token or key as a command argument.

The CLI pins the five installed source files and packaged Python files. A changed
source blocks before broker access; do not bypass the pins. It requires local
PAUSED / PREPARATION_ONLY state and LIVE_CLOSED adapter mode via the existing
read-only audit. It intentionally does not require fresh strategy quotes for
account review, and does not arm or consume signals.

Broker calls use the installed fixed GET-only account adapter, profile checks
before and after, and the installed signature verifier. Capture age is at most
30 seconds from sweep start. Local HMAC verifies locally pinned capture integrity;
it is not a broker-issued digital signature. The sweep is not broker-atomic.

Local application/adapter sources are read before and after capture and must
compare exactly. A concurrent local update may cause STOPPED_FOR_REVIEW.
This is a consistency check, not a lock across the remote account or a guarantee
that source state remains unchanged after return. There is no automatic retry.

## Output
Expected status even when reference matching succeeds:
BLOCKED_OWNERSHIP_AND_RISK_INTEGRATION_PENDING

For an empty account/history, current_bound_order_reference_count and
current_bound_fill_quantity are zero. Empty history never establishes zero P&L.
Missing current orders, unbound requests, missing application links, unrelated
orders, and prior-session acknowledgements remain explicit counts/gaps.
Reference fingerprints replace raw account/order/trade identifiers in summaries.
No capture or pin file is written by this checker.

## Still pending
The bridge authenticates the outer HMAC envelopes of bundles referenced by local
bindings, checks their pinned scope, read-only flags, declared profile verification
and internally consistent historical capture window. It uses the same local HMAC
algorithm as the installed pinned account adapter. This does not independently
authenticate the broker or revalidate nested cash signatures, contract selection,
quotes, signal/session correspondence or pricing policy. Old bundles remain
historical even when their signatures verify. Future-dated bundle capture windows
are rejected. Unreferenced stored bundles are outside this assessment. Order modification history, complete position
ownership reconciliation, fee evidence, realized/open net P&L, production daily
stop, actual reservation and release are not implemented here. In particular,
a matched BUY fill and a nonzero account position do not confer ownership.
Do not use summary flags or fingerprints as entry credentials.

No Store/Ledger constructors, application writes, broker mutations, service
restarts, risk-limit changes or execution activation occur.

## Validation
85 local tests passed: 31 supplied audit tests, 39 bridge tests and 15 position-reference tests.
Tests use explicit OFFLINE_FIXTURE local databases and synthetic signed capture
objects with a test pin. They exercise signature verification and reference
logic, not a real broker or runtime integration. The CLI accepts LIVE_CLOSED
only and uses the actual installed capture/verifier. VM validation is pending.
ResourceWarning was treated as an error. Sources stayed byte-identical in tests.


## Bundle signature output
The model name remains HILEGA_LIVE_OWNERSHIP_REFERENCE_BRIDGE_V1; review_version
identifies 3.0.0-entry-buy-position-references.
authenticated_historical_bundle_count counts distinct referenced outer envelopes.
bundle_signatures_assessed is true only if that count is positive. With no
bindings it remains false and NO_BOUND_PREPARATION_BUNDLES_TO_AUTHENTICATE is
reported. Nested financial evidence and full position ownership remain blocked.
No runtime deployment or restart is part of this package.


## Version 3 position reference review
position_reference_review compares current-session bound BUY fill quantities with
explicit instrument/product position rows in the same signed account capture.
It sums multiple entry orders by instrument/product, uses actual filled quantity
after a partial cancellation, and never treats an absent row as zero.

A matching result is REFERENCE_QUANTITIES_MATCH, not strategy ownership.
It requires at least one linked order; an empty account is not a proven strategy
baseline. Missing current orders, unacknowledged requests, acknowledgements
without application bindings, prior-session acknowledgements, unlinked account
orders, nonterminal entry orders, mismatched quantities and unlinked nonzero
positions block the reference comparison. Extra zero-quantity position rows do
not create exposure.

This version cannot attribute SELL exits, manual/external exits, prior-session
carry, order modifications, fees, mark-to-market P&L or durable lifecycle
ownership. Every original ownership/risk authority flag remains false, including
when current_entry_buy_position_quantities_match is true. The top-level blocked
status remains unchanged. It is not installed into the application entry path.
