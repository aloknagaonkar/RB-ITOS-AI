# Gross P&L and unallocated-fee stage v1

Fixture-only development stage; no live application integration or risk clearance.

## VM validation
    .venv/bin/python -m zipfile -e hilega-gross-pnl-stage-v1.zip hilega-gross-pnl-stage-tools-v1
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-gross-pnl-stage-tools-v1 -p 'test_*.py' -v
    .venv/bin/python -W error::ResourceWarning hilega-gross-pnl-stage-tools-v1/validate_gross_pnl_fixture.py

Expected: 196 tests pass and GROSS_PNL_FIXTURE_PREVIEW_PASS.
The tests and demonstration use synthetic fixtures, mock all fee-provider network
calls, and remove their temporary databases. They do not read real pins, .env,
account evidence, production databases or configuration. No restart is needed.
Use these validation commands only; live fee capture remains a separate workflow.

## What is added
preview_fixture_pnl consumes the locally signed state produced by staged
entry/exit fill reconciliation. It requires FIXTURE: scope, current-session
state no older than 30 seconds, exact order/trade totals, a two-order single
entry/exit lifecycle and consistent remaining/flat-reference quantities.

Realised GROSS P&L uses chronological moving-average cost accounting:
BUY fills add cost and quantity; SELL fills remove proportional current cost.
A SELL cannot borrow future BUY quantity. Same-time opposite fills require review.
This is a proposed FIXTURE accounting policy, not an approved production policy.
No fees are included in gross results.

Arithmetic uses exact rational numbers from decimal fill prices. Integer paise
is emitted only when exact. Otherwise the exact numerator/denominator is retained
and gross_realized_paise stays null pending an approved rounding policy.
No float rounding is silently adopted for risk inputs.

For remaining exposure, open gross and net P&L stay unknown without authenticated
mark evidence. Open gross zero is emitted only for a reconciled flat fixture
reference. Empty history is rejected rather than treated as zero realised P&L.

An optional aggregate fee capture is checked for its local signature, account,
date query, session and collection window. The provider's aggregate is shown for
comparison only. It is NEVER deducted from strategy gross or allocated across
fills. Zero aggregate charges do not establish strategy fee completeness.
The fee capture has no documented finality/data-as-of guarantee in this workflow.

strategy_fees_paise, realised net and open net P&L remain null. Production risk,
entry, release and execution flags remain false. No daily risk gate consumes
this preview. Original pending exit references and reservations are not cleared.

## Demonstration
Synthetic BUY 65 at INR100.05 and SELL65 at INR101 produces gross INR61.75.
The printed 6175 paise is a fixture example, not the user's trading result.
An aggregate fee report of zero still leaves net P&L unknown.
The partial-exit case preserves remaining exposure and unknown open net P&L.

## Validation and limits
196 local tests passed: 150 lifecycle + 26 fee provider + 20 gross P&L tests.
ResourceWarning was treated as an error. VM validation is pending.

This is single-session, single-entry/single-exit fixture logic. Carry positions,
multiple exits/replacement allocation, modifications, manual/external activity,
provider-authenticated mark prices, complete attributable fees and live ownership
are not implemented. Do not relabel live data as fixtures or remove the guards.

Production accounting/rounding policy, daily-loss and entry-cost values, durable
daily-stop integration, real reservation, runtime lifecycle integration and a
controlled pilot remain pending. No live trading readiness is established.
