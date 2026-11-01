# Second complete application-cycle candidate v3

## Failure and correction
V1: 127 passed / 14 failed-or-error cases. V2 fixed the final BUY evidence check
and reached 137 passed / 6 failed-or-error cases in the SELL path.

V2 inserted the SELL claim/adoption before its request row, in the same atomic
transaction. Cycle ownership was discovered only from request rows, so the new
pending SELL claim was temporarily misclassified as historical/unattributed.
The history-integrity check correctly refused that mismatched view.

V3 explicitly registers the derived SELL request ID in that transaction before
claim insertion. Current and historical readers share this pending-ID scope.
Registration rejects any pre-existing request, claim or adoption with that ID.
Pending claims must match the current parent, EXIT model/event-derived request ID
and identical application adoption. A new transaction starts with an empty
pending scope. Once committed, the real request row establishes ownership.
No unknown existing claim is broadly ignored; history equality stays mandatory.

Four regression cases cover the pending classification window, collisions with a
closed-cycle request, collisions with an orphan claim, and scope cleanup after
rollback. V2 expiry/quote-freshness regression cases are retained.

## VM commands
Keep v1/v2 and their failed reports. Download and extract v3 separately:
unzip hilega-second-application-cycle-v3.zip
.venv/bin/python hilega-second-application-cycle-v3/apply_and_test.py --repo "$PWD" --new-only

Expected focused 25 second-cycle cases. If those pass, rerun without --new-only
for the 147-case combined integration suite (prior 122 plus 25). The existing
expanded hilega-history-aware-preparation-v1 and hilega-application-cycle-close-v1
folders plus the 122-case PASS report remain required. The runner checks manifests,
15 installed source pins, Python syntax, counts and unchanged sources. It does
not overwrite previous candidates, installed code, controller state or services.

The workspace is unavailable. ZIP structure/CRC and payload hashes were verified
in memory; Python syntax and behavioral checks await your VM. No passing result
is claimed. The last completed integration checkpoint remains 122 cases.

## Retained connected scope
Actual Source preparation with synthetic signed inputs -> new history-aware
disabled preparation -> independent candidate claim/adopted BUY -> signed full
fills/position -> actual Source closed EXIT -> candidate owned SELL -> partial/
UNKNOWN/restart recovery -> signed flat -> cycle-specific gross closeout ->
archive/local reference retirement -> third-signal review against two archives.

Original full signed account captures are verified and preserved, never edited
or re-signed for projections. Old orders/trades and broker records must match
their archives exactly. Closed cycles contribute zero position; the full signed
position must match the current cycle's remaining quantity, even for the same
instrument. Selective recovery only updates the current request. Gross P&L is
counted per cycle's own order IDs, not all historical trades again.

All positive order paths use intercepted gate/transport with temporary synthetic
databases and mock credential providers. The actual HTTP hard gate remains in
place. Candidate authorities are caller-provided synthetic keys, not provisioned
trusted production authority. Entry and EXIT policy flags are not production
approval; PAUSED synthetic execution tests grant no live dispatch permission.
No automatic residual SELL, partial-entry resizing, cancel/reprice or opposite
BUY is added. Fees/net P&L remain incomplete, and local retirement is not broker
cash release. Journal chains are not external authentication; local database
transactions are not atomic with the remote broker.

Two complete application candidate cycles are the intended test scope, not an
unrestricted repetition or actual broker claim. Running worker/source hooks,
production authority/policy, fresh real broker validation, dependency/release
reconciliation, full release regression, managed deployment/rollback and an
explicitly authorized funded pilot remain pending. Live execution stays closed.

Return the focused report first. Overlapping suite counts are not unique totals.
