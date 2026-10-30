# Half-cash allocation and local reservation v1

## Operator-approved policy
Entry spending is capped at 50% of verified available trading CASH.
Daily maximum loss is deliberately unconfigured and is not required.
No separate fixed rupee maximum-entry-cost ceiling is introduced.
Premium plus the explicit fee/buffer amount must fit within the half-cash cap.

Current application preparation remains limited to one lot. This package
preserves that limit; it does not automatically increase quantity to use the
entire 50%. Whole-lot sizing and the freeze limit can leave budget unused.

## Validate on the VM
    .venv/bin/python -m zipfile -e hilega-half-cash-allocation-v1.zip hilega-half-cash-allocation-tools-v1
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-half-cash-allocation-tools-v1 -p 'test_*.py' -v
    .venv/bin/python -W error::ResourceWarning hilega-half-cash-allocation-tools-v1/validate_fixture.py

Expected: 30 tests and HALF_CASH_ALLOCATION_FIXTURE_PASS.
These commands use synthetic signed cash captures and temporary databases only.
They make no broker calls, do not read .env or real pins, change no application
database/configuration, and require no restart.

## Arithmetic
cash_paise is conservatively rounded down by the existing signed-cash verifier.
cap_paise = floor(cash_paise / 2)
order_cost_paise = limit_price_paise * quantity + fee_buffer_paise
quantity = one whole lot only when cap and freeze quantity permit it.

Price, lot size, freeze quantity and positive fee buffer are explicit integer
inputs. No net P&L or daily-loss value is required for this allocation calculation.
An absent daily-loss limit never creates a rejection reason in this module.

The fee buffer is provisional: this module does not certify that it covers final
fees. Contract, tick, quote quality, market/session entry window, approved pricing
and slippage validation remain separate mandatory application work.
The running candidate currently uses a provisional INR100 buffer; this package
does not change or approve that value for production.

## Cash authenticity and limitations
cash_checks.py contains only pure verification functions extracted from the
current signed-cash shadow gate, using the same local HMAC algorithm. It verifies
scope, capture status, cash field mapping, stable before/after funds, session and
account observations. Local signatures are not broker-issued signatures.
This module additionally limits age from sweep START to 30 seconds.

Current verifier refuses unexplained account orders, trades, exposure and
diagnostic issues. It therefore does not support an already-active/multicycle
live account without the remaining ownership/debit-attribution integration.
Do not remove that gate or relabel live records as fixtures to bypass it.

## Durable local book
ReservationBook creates a separate explicitly requested fresh reference-only
ledger. It never overwrites an existing file or adopts an application/adapter
database. Records bind account and exact policy; holds are locally signed.
BEGIN IMMEDIATE serializes reservations with FULL synchronous durability.
Freshness is rechecked after acquiring the lock and immediately before commit.
Hold and audit writes roll back together on injected failures.

Only one active local entry is allowed. Concurrent different plans cannot both
reserve, even when unused cap remains. Same-plan replay is idempotent; changed
price/quantity/buffer conflicts. Unknown outcome retains the entire held amount.
There is no release API. No broker debit is added back or treated as reflected
local cash. A local hold does not lock money at Upstox.

## Deployment status
This is a tested, staged policy/reservation component, not runtime wiring.
No application entry path or live transport has been changed. Production
execution, entry permission, real broker reservation and release remain false.
No daily-loss setting has been applied to the running configuration.

30 local tests passed with ResourceWarning treated as an error, including
half-cap boundaries, odd-paise flooring, fees/buffer inclusion, missing cash,
capture tampering/drift, concurrent attempts, retained unknown holds, rollback
and reopen. The fixture demo passed. VM validation is pending.

Next integration work is to commit a verified local reservation together with
the application's request/intent under the same transaction, then recheck all
live evidence before submission. Actual broker debit attribution, ownership,
live fills/exits/release and pilot acceptance remain pending.
