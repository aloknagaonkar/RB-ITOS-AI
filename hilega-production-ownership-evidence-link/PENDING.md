# Pending production items — after controller/adapter link VM PASS

Current installed workspace: SIMULATION_ONLY and PAUSED; production disabled.
The last verified actual cash capture had NO_CASH_CAPACITY. Do not fund solely to
pass an offline test. No live eligibility follows from synthetic test results.

| Item | Current evidence | Still required |
|---|---|---|
| Workspace controls and allocation | Installed update validated: 349 tests/build and 20 end-to-end checks PASS | Real broker execution port must observe the same controls |
| Broker adapter | 26 injected-response tests/demo and actual GET-only baseline PASS | Actual mutation behavior still untested; gate remains closed |
| Controller/adapter reservation linkage | 11 isolated tests/demo PASS | Production implementation with verified real allocation/mapping |
| Ownership evidence link | This package; VM results pending | Real signed account evidence, proven transport binding, release authority integration |
| Partial entry/cleanup and manual exit | Simulator and fixture behavior tested | Bound real fills, partial exits, cancel/fill race, zero oversell |
| Direct Upstox exit | Read-only account observations available | Attribute partial/full external exits; update app/P&L; block ambiguous activity |
| Cash/risk budget | 26 shadow-gate tests/demo; actual capture verified but capacity blocked | Debit/reflection accounting, fees/buffer, 50% reservation integration |
| Contract and quotes | Read-only preview rules tested | Fresh market-hours instrument/expiry/lot/offset/quotes and approved quality gates |
| Position/P&L UI | Simulator and account observation separation | Live option quotes, actual fills/charges, active/closed real trade display |
| Daily loss limit | Deferred by owner | Explicit setting and automated enforcement before enablement |
| Readiness and alerts | Simulator background watchdog tested | Consolidated production pre-market report, alerts/escalation, restart/backup tests |
| Pilot | Not started | Separately authorized supervised pilot after required engineering gates |

## Execution sequence

1. Run this ownership-link validation and inspect remaining quantities/assessment.
2. Build/stage a broker execution port that consumes verified ownership evidence,
   safely updates remaining quantities and releases linked funds exactly once.
3. Prove real cash/contract/risk inputs and external-exit/manual-exit behavior.
4. Validate real market-hours observation, pre-market checks and incident alerts.
5. Review the complete release and rollback plan, then separately authorize pilot.

No current package should be used to flip a production flag. Keep gate opening a
separate reviewed change; absent evidence must remain UNKNOWN/BLOCKED.

## Monitoring still required before enablement

Proposed IST schedule: 08:45 host/disk/clock/database/worker lease; 08:50 warmup,
completed-candle continuity and today bootstrap; 09:00 account/auth/IP/orders/fills/
positions/cash; 09:05 contract/quote/feed; 09:10 combined readiness, daily limits,
alert delivery and operator decision. Revalidate fresh evidence before every entry.

Continuous: worker and source age; authoritative Pause/stop generations; stale
funds/reconciliation; ambiguous attempts; partial/cancel/exit pending quantities;
external broker activity; owned exposure vs ledger; quote/P&L freshness; daily
loss/cash limits; disk/database/API failure; alert acknowledgement and escalation.

Failures block new entries. Continue safe position management and reconciliation;
Pause alone retains established positions. Unknown requests keep holds and must
not be blindly retried. Recovery stays paused until explicit Resume. None of the
proposed production readiness/alert automation is deployed by this package.
