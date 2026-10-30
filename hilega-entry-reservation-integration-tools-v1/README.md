# Application entry reservation integration v1 — staged code patch

This patch targets the actual application preparation transaction. It has NOT
been applied to the running VM. No service or configuration change is included.

## Changes
1. atomic_binding.py calls reserve_local inside the existing attached
   BEGIN IMMEDIATE transaction, after candidate/request validation and before
   inserting the closed-adapter request.
2. New cash_reservation.py records an application-owned, locally signed cash
   reservation alongside the plan, shadow hold, outbox and disabled request.
3. check-preparation-paused.py counts this new table separately and refuses
   clean-paused status if any local reservation exists, including an orphan.
   Existing activity_counts keys are preserved for compatibility.

The hold is linked to exact request, plan, outbox and shadow-hold fingerprints.
It references the same cost as the shadow hold; it is not a second independent
debit added to that hold. Current signed cash/quote/contract validations remain
in the actual upstream binder, and Source's final freshness checks are unchanged.

Policy: entry cost including explicit buffer must fit the 50% available-cash cap.
There is no daily-loss limit requirement and no fixed rupee entry-cost ceiling.
The existing one-lot, one-active-preparation, fresh-signal, pause/stop, ownership,
price-grid and closed-transport constraints remain unchanged. The fee buffer is
still provisional. Local reservations do not lock cash at Upstox or grant entry,
ownership, release or broker-execution permission.

No release API is added. Existing local reservations, including unknown outcomes,
require review before another preparation. There is no same-ID overwrite path.
Consumed source events preserve existing idempotency/restart behavior.

## Validate before applying
Extract into a fresh directory and run:
    .venv/bin/python -m unittest discover -s hilega-entry-reservation-integration-tools-v1 -p 'test_transaction.py' -v
    .venv/bin/python hilega-entry-reservation-integration-tools-v1/run_tests.py --repo "$PWD"

The runner verifies package and installed-source hashes, creates a temporary
import overlay, and runs six existing pytest files plus four new real-Source
integration checks. It uses the actual installed evidence, pricing, controller,
source and adapter modules with the proposed binder and reservation code loaded
from the overlay. Original code files are not replaced. The overlay is removed.

Tests use the existing synthetic signed provider and temporary application/
adapter databases. They do not arm the running application or send broker orders.
The runner writes only a public regression JSON report in this tool directory.
Expected report status is PASS with applied=false and production disabled.
Missing tests or baseline mismatches stop validation; do not change pins blindly.

## Validation limits
14 local unittest checks passed, including actual binder/SQLite transactions,
rollback after either write, exact cap, overlap prevention, signature tampering,
WAL rejection, closed transport and the paused-checker predicate.
These local tests substitute only upstream pricing/evidence inputs because the
VM application dependencies are not installed in the local build environment.

Full actual-Source pytest regression is pending on the VM. Do not apply before
that runner passes. The runner's pytest count depends on the installed test suite.

## Maintenance after successful VM validation
Runtime files are under runtime/. The two preparation modules belong under
backend/market_lab/hilega_preparation_runtime_v1/ and the paused checker belongs
at the repository root. Do not copy these over running services yet.
A reviewed paused maintenance apply/backup and restart verification is the next
step after the VM regression result. No database migration runs during staging;
tables are created only inside a future successful preparation transaction.

Existing pinned standalone review packages will need a reviewed source-version
refresh after the runtime binder changes; this package does not weaken their
pins or modify them automatically.

Production transport remains unconditionally closed. Fees/net P&L authority,
broker debit attribution, real account ownership and live lifecycle/pilot
acceptance remain separate work. Daily-loss configuration is optional under
the operator's current policy and is not demanded by this patch.
