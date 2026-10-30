# Exit fill lifecycle stage v1

Fixture-only development stage. No application deployment or live order authority.

## VM validation
    .venv/bin/python -m zipfile -e hilega-exit-fill-stage-v1.zip hilega-exit-fill-stage-tools-v1
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-exit-fill-stage-tools-v1 -p 'test_*.py' -v
    .venv/bin/python -W error::ResourceWarning hilega-exit-fill-stage-tools-v1/validate_exit_fill_fixture.py

Expected: 150 tests pass and EXIT_FILL_LIFECYCLE_FIXTURE_PASS.
Includes the previous 130 tests, so this also validates the acknowledgement-stage
tests if they have not yet been run on your VM.

All tests/demonstrations use synthetic fixtures, temporary databases and fake
transport. They do not read .env, real pins, real account snapshots or production
databases. Temporary data is removed. No service restart or activation.

## Reconciliation
reconcile_fixture_exit accepts FIXTURE: scope, a reference-only ledger and an
OFFLINE_FIXTURE adapter only. It locally verifies the signed synthetic account
capture, then validates the durable parent entry acknowledgement, exit reference,
atomic disabled request binding and exit acknowledgement receipt provenance.

All current orders must correspond exactly to that entry and exit. Contracts,
requested quantities, filled totals, trade identities, prices, timestamps and
session must match. Parent entry must be terminal and filled enough to support
the intended exit quantity.

BUY and SELL fills are processed chronologically. A SELL cannot borrow quantity
from a later BUY. Opposite-side fills at the same timestamp are ambiguous and
require review. Only explicit broker position rows can establish quantity;
missing is never flat. Unlinked orders and nonzero exposure block reconciliation.

A terminal partial cancellation retains its remaining position. Zero remaining
quantity is considered a flat FIXTURE reference only when both orders are
terminal and the explicit matching position row is zero. This does not authorize
live flatness, ownership, reversal or reservation release.

Prior fills may not disappear or change on later capture, even if a corrected
price preserves quantity. Older capture time, changed payload under the same
snapshot ID, terminal-order changes and fill regressions require review.
Persisted state is locally signed. State and snapshot references commit together;
an injected failure rolls back both. Repeated snapshots do not duplicate rows.

This covers one current-session entry with one explicitly bound exit. Multiple
exit orders, partial-exit replacement workflows, manual/external activity, prior
sessions and amendments are outside this stage. No retry or resubmission occurs.

## Limits
The writer only modifies its staged fixture reference ledger; the attached
fixture adapter is read-only and byte-identical after reconciliation.
Full live application integration remains unimplemented. Do not remove fixture
guards or relabel live evidence to bypass them.

Fees/net P&L, production daily-stop enforcement, risk policy values, real cash
reservation, account-wide lifecycle ownership and reservation release remain
pending. An acknowledgement is never a fill. Synthetic signatures are locally
generated test integrity checks, not broker-issued digital signatures.

## Validation
150 local tests passed (130 previous + 20 exit-fill tests), with ResourceWarning
treated as an error. The fixture demonstration passed. VM validation is pending.
No live broker integration or production readiness is established.
