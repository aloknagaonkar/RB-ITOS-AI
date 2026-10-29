# Hilega: shadow-to-live tracker

Updated 29 October 2026. This records terminal evidence supplied by the operator; it is not a live connection to the VM. Last supplied market/account capture: 11:03 IST. Current controller state must be read again before any operation.

**Goal:** confirmed signal → account/cash/risk checks → option and quantity → Upstox submission → fills → exit → reconciliation and hold release.

**Current milestone:** deployed PREPARATION_ONLY application with supervised processes. Fresh-signal admission is unverified. Production submission remains CLOSED_IN_CODE. No go-live date is established.

## Flow and evidence

| Step | Evidence completed | Acceptance gate still pending |
|---|---|---|
| Confirmed signal | Shadow decisions, snapshot links, journal verification and selected replay checks tested | Fresh, non-reconstructed signal admitted by the running preparation route |
| Account/cash/risk | Pinned account read access works. Signed capture reports market open, cash ₹0 before/after and half-cash cap ₹0. Captured candidates reject insufficient capacity | Compare funds mapping with pinned Upstox display; approve and validate production capital/exposure/daily-loss limits |
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

## Latest capture

Evidence folder: `data/research/hilega-session-readiness-qyjt3xpg`.

| Candidate | Instrument | Quantity | Provisional cost | Result |
|---|---|---:|---:|---|
| Bullish | NSE_FO\|53796 | 65 | ₹9,960.50 | NO_CASH_CAPACITY; HALF_CASH_CAP_EXCEEDED |
| Bearish | NSE_FO\|53835 | 65 | ₹10,207.50 | NO_CASH_CAPACITY; HALF_CASH_CAP_EXCEEDED |

Quotes were approximately 0.6 seconds old with no quote-specific rejection. `tick_units_verified` remained false. This was a read-only candidate assessment, not automatic signal admission or an executed trade. Do not reuse these prices for later action.

## Next milestone: bounded preparation rejection test

1. Keep the controller PAUSED while preparing the test. Funds-display comparison remains UNCONFIRMED; “go ahead” is not evidence that the display matches.
2. Recheck today's session, fresh source/heartbeat, service identity, journal prefix, closed transport, PREPARATION_ONLY route and empty application/adapter activity.
3. Prepare and test the session harness before arming anything. It must have a finite deadline, a durable independent pause deadline, single-attempt command IDs, explicit handling of uncertain acknowledgements, and pause/cleanup on error or interruption. Never automatically retry Resume.
4. If a zero-cash rejection test is authorized, preserve the measured cash result. Do not insert artificial balances, replay an old event into the production journal, loosen freshness checks or enable broker transport.
5. Admit only a newly confirmed eligible ENTRY after controlled Resume. An exit/reversal blocked for missing ownership does not establish entry/cash-path success.
6. Capture the source event identity and fresh signed account/quote evidence. Expected zero-cash outcome: insufficient-capacity rejection with no plan, hold, outbox, adapter request, attempt, receipt or broker order. Any different outcome requires review.
7. Return to PAUSED on the first relevant outcome or deadline. Recheck all counts, request/receipt history, source health and control state; retain a private assessment report.
8. No eligible entry before the deadline means INCONCLUSIVE, not PASS. Successful funded preparation and the live execution lifecycle remain separate milestones.

**Current test status: NOT ARMED; harness not yet delivered; no live-signal admission clearance.**

## Go-live release gate

Before pilot approval: confirm applicable broker authentication/network/permission prerequisites; approve funds mapping, risk and pricing policies; verify submission/fill/exit/reconciliation/release behavior including failure recovery; establish monitoring and an emergency-stop procedure; review deployment/rollback and credentials; complete an isolated full-lifecycle rehearsal. Tests and read-only connectivity alone do not clear live trading.
