# History-aware next disabled preparation candidate v1

This isolated package is delivered through a new GitHub candidate branch because
the temporary execution workspace disconnected. No Python syntax or behavioral
tests were run during packaging. ZIP structure/CRC and payload hashes were
verified in memory; apply_and_test.py compiles all Python files on your VM before
running tests. Positive order branches remain intercepted in temporary synthetic
databases. Nothing is installed into the running application.

## Run
From ~/RB-ITOS-AI, place this ZIP here and unzip it, then:
.venv/bin/python hilega-history-aware-preparation-v1/apply_and_test.py --repo "$PWD"

Expected combined 122 cases: the previously passing 104 plus 18 new cases.
--new-only selects 18 new cases. The existing expanded
hilega-application-cycle-close-v1 folder and its 104-case PASS report are required.
This bundle imports that immutable prior candidate; it does not duplicate or
overwrite it. Prior package hashes and all 15 reviewed application pins are
checked before tests. This is NOT the full repository release regression.

## What changes in the workflow
After the previous candidate retires a flat cycle's five local active references,
prepare_next_disabled verifies the closed account/adapter history, archived journal
prefix, a new unconsumed ENTRY, explicit post-Resume controller state, bridge health,
signed matching account/cash captures, fresh quotes/tick grid and half-cash cap.
It creates exactly one new disabled BUY draft, plan, outbox, binding and signed
local cash reservation, plus a signed admission receipt. The broker's old requests,
attempts, receipts and claims remain intact. The Source consumption/cursor and
controller PAUSED transition share the same attached DELETE/FULL transaction.
Failures roll back both databases. Same-input replay and concurrent callers do
not create another request or reservation.

The dedicated binding/admission models are deliberately distinct from the original
first-entry binding. The unchanged Source is NOT patched to bypass its history
guard. Existing first-entry execution adoption functions cannot be assumed to
accept this new historical context: next-BUY execution adoption is still pending.
The new request is PREPARED, order_id is null, submission_enabled=false, all
authority flags remain false and the installed adapter hard gate still refuses.

## Scope limits
Only the immediately next consecutive source record can be prepared. Nonexecution
records must be processed explicitly before a later ENTRY; the function will not
skip intervening records silently. A new CALLER invokes this candidate API; no
running service hook or automatic poller is installed.

The single generic historical-activity cash blocker is attributed ONLY after exact
closed-history matching. All other evidence blockers remain. A signed reservation
is an application-local reference, not a broker cash lock. Fees/net P&L remain
incomplete; no broker cash release or live execution clearance is introduced.
History signatures/journal chains do not prove remote broker atomicity or external
journal authorship. Current controller review state is returned to PAUSED after
the preparation; this is not ARMED live dispatch authorization.

## Milestones
- Application BUY/fill/EXIT/SELL/flat + closeout/archive/local retirement and
  next-entry eligibility review: prior 104-case synthetic integration PASS.
- Next fresh disabled application preparation: CURRENT 18 new / 122 combined VM
  checks pending.
- History-aware execution adoption for that next BUY: pending.
- Source-worker automatic wiring, production authority/policy, dependency/release
  reconciliation, complete regression, managed deployment/rollback and authorized
  funded pilot: pending.
- Live automatic trading is disabled; no installed source/service is changed.

Return VM-VALIDATION.json. Do not count overlapping suites as unique totals.
