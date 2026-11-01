# Milestone checkpoint

| Step | Evidence / status |
|---|---|
| Reusable synthetic cycles through 10 cycles | Prior VM pass |
| Durable journal, reversal exit-first, working partial SELL tracking | Prior 163-case full VM pass |
| Closed worker boundary, heartbeat, bounded restart, staged unit verify | Prior 13-case targeted VM pass |
| Actual worker identity and related running services | VM inspection supplied; source SHA pinned in this package |
| Application closed hook staging | Current step; 12 targeted / 179 full VM checks pending |
| Actual Source data-contract and dependency-manifest integration | Pending review |
| Managed closed application deployment and rollback exercise | Pending |
| Fresh broker evidence, pricing/partial policy, trusted authority | Pending |
| Authorized funded pilot and unattended production operation | Pending |

Why this step: the running script currently has no preparation_tick wrapper. Staging the exact call-site change lets us review where preparation hands off while the execution boundary stays closed.

Immediate opposite BUY, automatic residual SELL, and broker cancel/reprice remain disabled. Actual fees/net P&L completeness and production reservation-release policy remain pending; protective exits must not wait for fee accounting. Production execution is disabled, and production readiness is not established.
