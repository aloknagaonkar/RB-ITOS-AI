# Application cycle closeout, retirement and reentry review — v1

## Connected workflow

Prior candidate: Source preparation -> adopted BUY -> signed fills/position -> actual Source closed EXIT -> candidate SELL -> terminal signed flat.

This bundle adds: terminal-flat lifecycle closeout -> immutable signed cycle archive -> atomic retirement of active LOCAL references -> exact attribution of old account/adapter history -> fresh post-Resume next-entry ELIGIBILITY REVIEW.

It does not create the next preparation or enable the next BUY. The original Source rejects existing adapter activity, and its closed-exit history guard also needs a dedicated history-aware integration. This package reports application_source_reentry_integrated=false instead of disabling those guards. No original worker or source is modified.

## VM commands

```bash
cd ~/RB-ITOS-AI
unzip hilega-application-cycle-close-v1.zip
.venv/bin/python hilega-application-cycle-close-v1/apply_and_test.py --repo "$PWD"
```

Default expected 104 integration cases: the previously passing 79 plus 25 new cycle-close/retirement/reentry-review cases. Optional --new-only selects the 25 new cases. Default combined run is preferred for the milestone. These suites overlap prior results and are not a full repository release regression.

The runner requires the previous 79-case lifecycle VM PASS report with broader integration reexecuted, verifies package hashes and the same 15 exact reviewed source pins, and runs only isolated folder-local tests. It does not install HOME modules, modify installed sources, restart services, access live application databases or load real broker credentials. Positive order branches are intercepted in temporary synthetic fixture databases. Here only syntax, test-case enumeration, hashes and ZIP integrity were checked; no behavioral pytest was run during package creation.

## Closeout semantics

A lifecycle closeout requires an acknowledged SELL, exact signed order/trade/position agreement, terminal orders and an explicit zero position row. It preserves the original account snapshot, request/attempt/receipt/claim rows, signed local reservation and application source references, and binds them to the confirmed EXIT journal record. It rechecks before committing. Durable replay needs no new capture and grants no current clearance.

Gross realized P&L is calculated exactly in paise from signed trade prices/quantities. Fees are not fabricated: fees_complete=false, realized_net_pnl_paise=null and financial_closeout_complete=false. Protective SELL and flat recording do not depend on fee availability. This is NOT a final financial accounting release.

## Local retirement semantics

Retirement requires a signed closeout, unchanged source records, a fresh terminal-flat capture and a PAUSED controller with no pending stop. It archives the entire cycle before deleting exactly its active preparation plan, shadow hold, outbox, binding and local cash reference in the same application transaction. Interruption restores them all. Broker records, signatures, evidence bundles, journal records, candidate adoptions and historical position reviews are preserved.

Local reference retirement is not release of broker cash. broker_cash_release_assessed=false and reservation_release_permission=false. The controller remains PAUSED. No automatic new entry is created or armed. Historical replays verify signed archive bindings and never collect or retire another cycle.

## History-aware next-entry review

Eligibility review requires: no active local cycle or controller execution; exact signed archived history attribution for every current account order/trade and adapter request/attempt/receipt/claim; explicit flat position rows; unchanged archived journal prefix; a new single confirmed ENTRY not previously consumed; fresh post-Resume timestamp within the entry window; current ARMED/reconciled controller/version with no pending stop; healthy same bridge lease; and fresh signed market/cash evidence with identical account rows.

Only after exact closed-history matching may the existing cash gate's single generic historical-order-activity blocker be treated as attributed. No other blocker is discarded. Current ATM/contract selection, one-lot quote/grid checks, positive fee buffer and the fresh half-cash cap still apply. Old capacity is never reused. The result is REVIEW ELIGIBILITY ONLY: entry_permission=false, no preparation/request/hold is written and automatic_next_entry_enabled=false. It is not a grant, a production pricing approval or a claim that the unchanged Source now supports repeat application cycles.

The tests update temporary controller/health rows synthetically to represent an explicit Resume; this runner does not arm any real controller. No production authority is provisioned. Actual fees, next-entry preparation/adoption integration, dependency/release reconciliation, full regression, managed deployment/rollback, fresh broker validation and an authorized funded pilot remain pending.

## New coverage

25 cases cover exact gross/no fake fees, closeout replay/rollback/open SELL/expiry, evidence-preserving retirement, retirement replay/rollback/expiry/tampering/concurrency, attributed fresh reentry review, lower fresh cash, old/consumed/pre-Resume signals, external orders, missing flat rows, archive tampering, reappeared active references, cash/account discrepancies and stale captures.

Return VM-VALIDATION.json after running. Production execution remains disabled and runtime_deployed=false.
