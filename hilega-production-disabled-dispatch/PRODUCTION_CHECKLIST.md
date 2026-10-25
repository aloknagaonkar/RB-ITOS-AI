# Production enablement checklist and monitoring plan

Status based on VM evidence supplied on 25 October 2026. Production execution is
DISABLED; the installed workspace is SIMULATION_ONLY and PAUSED. Actual cash
capture verified but returned NO_CASH_CAPACITY. No trading readiness is granted.

## Completed within stated scope

| Area | Evidence | Scope limit |
|---|---|---|
| Static IP/auth/account pin | Actual read-only capture verified | Not mutation permission |
| Workspace controls | 349 regression tests and staged build passed; update applied | Simulator only |
| Reader/API/CLI lifecycle | 20 end-to-end checks PASS | Synthetic journal/cash/fills; no browser clicks |
| Process recovery and concurrency | 25 standalone controller tests PASS | Prototype; installed regression coverage is separate |
| Intent binding | 22 tests + demo and read-only baseline PASS | No live acknowledgement provenance |
| Real cash shadow gate | 26 tests and offline demo PASS; fresh read-only capture verified | Current capacity blocked; debit attribution NOT_VALIDATED |
| Disabled dispatch outbox | Package prepared; VM tests pending | No network transport; no application integration |

## Remaining implementation/validation sequence

| Step | Work required | Evidence before closing |
|---|---|---|
| 1 | Validate this disabled outbox and review immutable requests | VM unit tests and demo PASS; requests remain unsent |
| 2 | Design/install the real execution adapter behind a closed production gate | Atomic reservation/intent; actual transport attempt and receipt provenance; no caller-supplied order-ID adoption; no blind retry |
| 3 | Broker reconciliation and external exits | Bound order/fill/position quantities; partial fills; cancel/fill race; direct Upstox partial/full exit; ambiguous attribution blocks entries |
| 4 | Real cash/reservation accounting | Fresh net cash, holds, fees/buffer and reflected-debit treatment verified; no unsafe overlap credit or automatic unknown-hold release |
| 5 | Market-hours observation and exit visibility | Fresh eligible contract/quotes, feed entitlement, no missing signals, current broker P&L/closed-trade evidence, UI/CLI manual exit paths |
| 6 | Finish risk settings and operational controls | Initial one lot/ATM, configurable later; 50% cap; daily loss limit explicitly set; Pause/Resume rules; alerts and owner response tested |
| 7 | Controlled pilot and explicit enablement | All readiness evidence fresh; deployment/rollback ready; supervised minimum-size pilot separately authorized; verify fills/exit/cash end to end |

Steps overlap in engineering, but the pilot cannot substitute for missing basic
controls. No automatic production enablement after tests. Zero cash is not a
software failure and no deposit is required for offline development. Daily loss
limit was deferred by the owner; it remains an enablement blocker, not unlimited.
The first real pilot must not be used to discover whether Pause works.

## Proposed pre-market schedule (IST)

This is an operational schedule to implement, not an already-running automation.
Run on intended trading sessions; validate the exchange calendar/session status.

| Time | Checks | Failure behavior |
|---|---|---|
| 08:45 | VM/disk/clock/NTP, DB access/integrity, backup recovery, one worker/lease owner, correct deployed policy/version | Keep entries blocked; report exact failing component |
| 08:50 | Historical warmup and exact completed candles; today's session bootstrap; journal continuity/cursor | No entry permission on missing/reconstructed/stale evidence |
| 09:00 | Actual account identity/token/IP access; complete orders/trades/positions; unknown requests; external activity; fresh real cash | Unknown exposure stays unknown; no automatic retry or auto-flat claim |
| 09:05 | Contract/expiry/lot/offset mapping; quotes/spread/depth; market state; selected-feed entitlement | Reject ineligible/stale contracts; no fallback to guessed metadata |
| 09:10 | Combined readiness report; daily loss/risk settings; Pause persists across restart; alert delivery/acknowledgement; operator decision | Remain PAUSED unless all required checks pass and operator explicitly resumes |
| Before first entry | Recheck authoritative control version/session, fresh signal, feed/reconciliation/funds, contract/quote, reservation capacity | One blocked reason recorded; no BUY on stale or incomplete evidence |

A successful 09:10 report does not authorize a later entry with stale evidence.
Resume means next fresh signal, not replay of earlier continuation/armed state.

## Continuous monitoring and response

| Signal | Required monitoring | Response |
|---|---|---|
| Worker/reader liveness | PID/lease, heartbeat age, restart count, duplicate worker attempts | Durable entry pause; no automatic Resume on recovery |
| Market source | Last completed candle/decision, source age, missing or regressing journal chain, feed gaps | Stop new entries; preserve broker reconciliation and safe exits |
| Control state | Requested/handled stop generations, version/session, pending cleanup, command receipt | Show STOP REQUESTED until handled; show pending exposure/exit separately; never label flat from a timeout |
| Broker lifecycle | Attempt/ack/fill IDs, response timeout, partial entry, cancel pending, exit pending, remaining owned quantity | Retain holds; no duplicate POST/SELL; escalate unresolved order immediately |
| Account reconciliation | Orders/trades/positions consistency, unmapped/external changes, evidence freshness | Block new entries; reconcile attributable partial/full exits; do not invent P&L |
| Cash/risk | Fresh available cash, total held and unreflected holds, capacity, fees/buffer, daily realised/unrealised risk | Reject over-cap entry; retain unknown holds; apply agreed daily stop |
| Quotes and position P&L | Quote/trade age, bid/ask, option instrument/session, P&L timestamp | Label stale/unknown; never display old P&L as current; do not block known-safe exit merely for entry-only gate failure |
| Platform health | API errors/latency, disk space/write failures, clock changes, service restarts | Fail closed for entries; notify operator with actionable reason |
| Alerts | Delivery + acknowledgement + escalation test | A log line alone is not alert delivery; unresolved alerts remain visible |

Current tested simulator thresholds: heartbeat limit 15 seconds; source limit
390 seconds; cash/reconciliation freshness 30 seconds. These are existing simulator
settings, NOT a complete approved production SLA. Contract-preview thresholds are
still draft. Final production cadence must fit broker rate limits and exit-risk
requirements; it must be tested under expected load.

## On an incident

1. Persist Pause; ensure all entry/reversal BUY paths observe it.
2. Reconcile accepted/pending/unknown requests without blind resubmission.
3. Continue management of established positions; Pause alone does not close them.
4. For manual/direct-broker exits, verify remaining owned quantity before any SELL.
5. Escalate broker/API/exit uncertainty to the operator; do not claim cancellation,
   closure or a cash release solely from an HTTP acknowledgement or missing row.
6. Recovery remains paused. Recheck readiness and require an explicit fresh Resume.

A broker outage cannot be solved by the application's Pause flag. Emergency
broker access and operator response need to be rehearsed before the pilot.

## End-of-session controls

Verify terminal orders, remaining owned exposure, unresolved requests and holds;
reconcile fills/charges/P&L; archive the private audit trail; verify the backup;
record any manual broker changes. Next session begins unarmed, with no previous
signal replay. Outstanding exposure/unknown outcomes survive session changes and
require recovery; they must not be discarded by resetting the date.

## What is NOT yet deployed

No consolidated production readiness daemon, real execution transport, real debit
attribution, automatic external-exit attribution, real-order manual exit, live
broker P&L or production alert/escalation service is provided by this package.
The existing simulator API watchdog and UI/CLI controls remain the tested installed
mechanisms. Do not interpret this proposed monitoring plan as an active service.
