# Hilega: shadow-to-live tracker

Updated 29 October 2026. This records terminal evidence supplied by the operator; it is not a live connection to the VM. Last supplied market/account capture: 12:23:42 IST. Current controller state must be read again before any operation.

**Goal:** confirmed signal → account/cash/risk checks → option and quantity → Upstox submission → fills → exit → reconciliation and hold release.

**Current milestone:** deployed PREPARATION_ONLY application with supervised processes. Fresh-signal admission is unverified. Production submission remains CLOSED_IN_CODE. No go-live date is established.

## Flow and evidence

| Step | Evidence completed | Acceptance gate still pending |
|---|---|---|
| Confirmed signal | Shadow decisions, snapshot links, journal verification and selected replay checks tested | Fresh, non-reconstructed signal admitted by the running preparation route |
| Account/cash/risk | Pinned account read access works. Signed capture reports market open, cash ₹0 before/after and half-cash cap ₹0. Captured candidates reject insufficient capacity | Operator declared the zero-cash display comparison during test runs; broader production funds mapping and capital/exposure/daily-loss approvals remain pending |
| Option/quantity/price | One-lot preparation and disabled limit candidate deployed; quote freshness and price-grid components tested | Production tick-unit, pricing, slippage and fee approvals; actual quote/candidate linkage for a fresh signal |
| Request binding | Atomic local binding enabled; admission-wait correction deployed | Observe consistent plan/hold/outbox/adapter binding in the running application; local binding is not broker cash locking |
| Upstox submission | Isolated adapter components tested | Implement and authorize live routing, acknowledgement/timeout handling and durable duplicate prevention |
| Fills/ownership | Receipt and lifecycle components tested with fixtures | Actual order/trade mapping, partial fills, cancellations, unknown outcomes and strategy ownership |
| Exits | Strategy exit logic tested in shadow/offline scope | Broker exits, partial/manual/external exits, disconnect/restart and emergency-stop behavior |
| Reconciliation/release | Review components tested offline | Live terminal-state proof, attribution, safe accounting and hold release |
| Pilot | Not started | End-to-end rehearsal, production prerequisites, explicit pilot authorization and supervised minimal approved exposure |

## Operations

- API 4169, worker 4154 and source 4171 were verified active under user systemd; all three enabled and user lingering enabled.
- API health: `ok`, execution `not_enabled`.
- Safety check at 10:59 IST: PAUSED, PREPARATION_ONLY, fresh source, matching PIDs, journal caught up and all reported activity counts zero.
- Restart/start/stop/status entry points integrated with service control. Existing observer and publisher hooks retained. These hooks' older raw-PID/force-kill handling has not been hardened by this change.
- Logout/reboot recovery and an end-to-end use of the modified restart script have NOT been exercised. Avoid testing them during signal-admission work.
- Launcher binds to a saved `.env` hash and private startup configuration. Token/configuration changes need a reviewed refresh; do not edit the saved hashes merely to suppress a rejection.
- Keep private startup files, stage configuration and credential backups out of GitHub and shared attachments.

## Archived capture at 11:03 IST

Evidence folder: `data/research/hilega-session-readiness-qyjt3xpg`.

| Candidate | Instrument | Quantity | Provisional cost | Result |
|---|---|---:|---:|---|
| Bullish | NSE_FO\|53796 | 65 | ₹9,960.50 | NO_CASH_CAPACITY; HALF_CASH_CAP_EXCEEDED |
| Bearish | NSE_FO\|53835 | 65 | ₹10,207.50 | NO_CASH_CAPACITY; HALF_CASH_CAP_EXCEEDED |

Quotes were approximately 0.6 seconds old with no quote-specific rejection. `tick_units_verified` remained false. This was a read-only candidate assessment, not automatic signal admission or an executed trade. Do not reuse these prices for later action.

## Next milestone: bounded preparation rejection test

1. Keep the controller PAUSED outside a specifically authorized bounded test. Operator zero-cash display confirmation was explicitly supplied with the run flags; reconfirm current circumstances before later sessions.
2. Recheck today's session, fresh source/heartbeat, service identity, journal prefix, closed transport, PREPARATION_ONLY route and empty application/adapter activity.
3. Prepare and test the session harness before arming anything. It must have a finite deadline, a durable independent pause deadline, single-attempt command IDs, explicit handling of uncertain acknowledgements, and pause/cleanup on error or interruption. Never automatically retry Resume.
4. If a zero-cash rejection test is authorized, preserve the measured cash result. Do not insert artificial balances, replay an old event into the production journal, loosen freshness checks or enable broker transport.
5. Admit only a newly confirmed eligible ENTRY after controlled Resume. An exit/reversal blocked for missing ownership does not establish entry/cash-path success.
6. Capture the source event identity and fresh signed account/quote evidence. Expected zero-cash outcome: insufficient-capacity rejection with no plan, hold, outbox, adapter request, attempt, receipt or broker order. Any different outcome requires review.
7. Return to PAUSED on the first relevant outcome or deadline. Recheck all counts, request/receipt history, source health and control state; retain a private assessment report.
8. No eligible entry before the deadline means INCONCLUSIVE, not PASS. Successful funded preparation and the live execution lifecycle remain separate milestones.

**Current test status: BOUNDED SESSION COMPLETED, INCONCLUSIVE_NO_ELIGIBLE_ENTRY. V3 passed 55 VM tests. The latest run captured zero-cash evidence at 12:23:42 IST, attempted controlled Resume, completed the five-minute observation window and verified PAUSED cleanup. No broker submission was attempted. No eligible ENTRY arrived, so live signal-to-cash rejection and successful funded admission remain unverified. Direct refresh was exercised: dashboard age 30.5 seconds, direct evidence age 0.414525 seconds, pin verified before and after. Latest report: `data/research/hilega-preparation-session-test-2rxqunub/report.json`. Preserve all earlier reports. The result does not independently establish that the external deadline timer itself fired.**

## Go-live release gate

Before pilot approval: confirm applicable broker authentication/network/permission prerequisites; approve funds mapping, risk and pricing policies; verify submission/fill/exit/reconciliation/release behavior including failure recovery; establish monitoring and an emergency-stop procedure; review deployment/rollback and credentials; complete an isolated full-lifecycle rehearsal. Tests and read-only connectivity alone do not clear live trading.

Next action: inspect current shadow ownership/setup context read-only, then select a bounded window before a new eligible entry or in a future trading session. No code change is required by an inconclusive outcome. Do not replay old entries, manufacture signals, loosen rules or automatically extend arming.


### Independent risk-development milestone

Standalone offline daily-loss input reviewer implemented; 39 VM tests passed and the missing-input example correctly returned BLOCKED. Missing limits/PNL/fees/reconciliation/latch state block review. Proposed no-profit-offset accounting and budget checks grant no entry or execution authority. No production amounts were chosen, no daily-loss latch was persisted and no running application was changed. Production risk evidence, approval, durable enforcement and wiring remain pending. Latest supplied shadow context stayed BEARISH through 12:45 IST; no pending setup during the read-only watch. The 12:30 shadow entry is historical and must not be adopted or replayed.

### Durable latch rehearsal — VM validation completed

A fixture-only SQLite latch package passed all 76 tests on the operator VM (39 reviewer tests plus 37 latch tests), with ResourceWarning treated as an error. The VM demo returned ISOLATED_LATCH_DEMO_PASS and removed its temporary database. Tests cover commit persistence across separate writer/reader processes, concurrent state updates, immutable same-session policy, idempotent reviews, rollback of latch/audit/rollover changes, and explicit reconciled fixture session rollover. Real account scopes, unrelated databases, symlinks and WAL conversion are rejected. All outputs deny entry and execution authority. VM fixture validation is complete; production integration and authenticated live P&L remain unimplemented. No running application/configuration/database was changed.

Completed: offline reviewer VM validation; fixture latch implementation, local validation and 76-test VM validation.
Pending: authenticated live strategy-owned P&L and fees; approved account-specific risk policies; durable production entry-boundary integration; remaining signal admission, submission, fill, exit, reconciliation and pilot gates. No production loss limit is selected or enforced by the fixture package.

## Current engineering priority

Next work is an evidence-to-risk integration contract: identify durable acknowledged request/receipt/order/trade ownership and complete fee/P&L sources; keep unavailable ownership/P&L blocked; then rehearse atomic risk, latch and reservation checks together in isolation before runtime integration. A cached flat account or shadow trade is not proof of strategy-owned live P&L. Production risk amounts/approvals and live submission authorization are still pending. No additional runtime activation is justified by the fixture tests.
