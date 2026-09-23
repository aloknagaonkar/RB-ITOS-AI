# Phase 7C — Shared Exact Entry/Exit Recovery and Restart-Safe Pending Exits V1

## Scope and safety

This patch uses the same `HilegaMilegaOptionShadowLifecycleV1` engine for **live shadow** and `HilegaMilegaHistoricalFunctionalParityReplayV1`. The strategy entry/exit rules, expiry policy, ATM±2 CE set, underlying points and order safety settings do not change. There are no orders, quantities, slippage assumptions, synthetic option quotes, nearest-minute substitutions or automatic expiry changes.

## Behavior

- An exit still refers to the original exact causal option-minute **OPEN** (structural: signal 5-minute bar + 5 minutes; cutoff: 14:55 one-minute OPEN). If any exact option minute is unavailable, the lifecycle atomically switches to `PENDING_EXACT_EXIT` and saves the fixed `pending_exit_boundary`/reason. It becomes economically inactive; updates after the intended exit are rejected.
- The coordinator moves that pending trade into an independent signal-keyed collection; newer signals have their own lifecycle. Every later poll may retry only the original five instruments at the original exit timestamp. A successful retry emits `OPTION_SHADOW_LIFECYCLE_EXIT_RETRY/CLOSED` and supplies the five original exact exit opens and realized premium-point returns. An unavailable exact minute cannot be replaced.
- An initially `INCOMPLETE` exact entry retains its originally frozen candidate set; a live tick may retry the original entry boundary **only after the minute is completed and while the original underlying trade remains active**. The audit distinguishes the entry retry. This is late *observation of the originally fixed open*, not a claim that an executable fill happened at the earlier time. A missing entry unresolved by underlying exit stays unpriced.
- After a same-session process restart, the coordinator verifies the append-only step-audit chain and restores pending exits only from their original complete audited five-leg identities and exit boundaries. It never silently substitutes newly listed contracts. Older immutable audit records remain untouched.
- The read-only dashboard adds `pending_exit_count` and distinguishes `PENDING_EXACT_EXIT` from completed, active and incomplete. No pending premium change contributes to realized P&L. Legacy bad post-exit updates are ignored after the first recorded exit attempt. The UI makes pending-exit data status explicit.
- Historical parity adapter now only supplies **already-completed** option minutes as of simulated clock time. Its option lifecycle/audit uses the same coordinator implementation as live shadow.

## Explicit limits / follow-up gates

1. The September 23 existing `INCOMPLETE_EXIT` and post-exit legacy audits are preserved; the patch does **not** rewrite old audit chains or invent an old missing exit price. A separate evidence-verified immutable reconciliation sidecar would be needed for those pre-patch records.
2. Pending exits can automatically resume after a **same-session** restart using intraday data. Overnight reconciliation is **not implemented** because the current live option source serves intraday only. Next-day unresolved entries remain visible as historical unavailable, not fake zero-P&L.
3. A real recorded-session historical/live **event-for-event** diff is still pending; unit tests prove shared-function behavior and simulated-clock data gating, not parity against September 23 captured provider data.
4. If a process restarts while an initially incomplete exact **entry** has not yet been successfully audited, that entry must be separately marked backfilled/recovered in a future explicit audit enhancement; this patch's same-session pending-**exit** restore is verified from an authenticated audit record.
5. Automatic expiry resolution from provider contract master remains a separate phase. Keep explicit verified `HILEGA_MILEGA_OPTION_EXPIRY` until implemented.

## Installation (on RB-ITOS-AI branch feature/pcr-foundation)

Save the ZIP to the VM, then from `~/RB-ITOS-AI`:

```bash
# Preserve your exact current work and inspect before applying.
git status --short
unzip -l /path/to/hilega_milega_phase7c_exact_exit_recovery_v1.zip
unzip -o /path/to/hilega_milega_phase7c_exact_exit_recovery_v1.zip
source .venv/bin/activate
python -m pytest \
  tests/test_hilega_milega_phase7c_pending_exit_v1.py \
  tests/test_hilega_milega_option_shadow_lifecycle_v1.py \
  tests/test_hilega_milega_live_shadow_v1.py \
  tests/test_hilega_milega_trade_dashboard_v1.py \
  tests/test_hilega_milega_audit_report_v1.py \
  tests/test_hilega_milega_functional_parity_replay_v1.py \
  tests/test_live_shadow_step_audit_v1.py -v
cd frontend && npm run build
```

Do NOT merge generated artifacts into old audit JSONL files. Do NOT run another Hilega worker concurrently.

Outside market hours, after tests: identify the Hilega PID from `/proc/<pid>/environ`, stop **only** that PID, and restart with explicit `LIVE_SHADOW_STRATEGY=HILEGA_MILEGA_BULLISH_SHADOW_V1` and verified `HILEGA_MILEGA_OPTION_EXPIRY`. Restart the `market_lab.runtime api` service only after identifying how it is managed; do NOT touch SQLite bridges 8765/8766.

## Validation checklist (preserve/update after each release)

- [x] Shared pending-exit engine, same historical/live coordinator
- [x] Exact original exit minute only; frozen identity and expiry
- [x] No future post-exit updates or MFE/MAE contamination
- [x] Exact late exit retry with five independent CE premiums
- [x] New signals do not overwrite pending exits
- [x] Audit-verified same-session restart recovery
- [x] Exact missing entry retry in the same still-active signal
- [x] Simulated historical clock hides future/forming option minutes
- [x] Pending/exact-exit dashboard state, legacy post-exit update filtering
- [x] Detailed audit includes entry/exit retry fields
- [x] Safety: observation-only, no quantity/orders
- [ ] Verify full regression and frontend build in actual VM repo
- [ ] Verify newly observed complete five-strike exit during next live session
- [ ] September 23 recorded-session historical/live normalized event diff
- [ ] Natural active-trade 14:55 cutoff exact-option exit
- [ ] Verify Dashboard V3 expandable Audit and exact five CE entries/exits in browser
- [ ] Offline reconciliation design for pre-patch missing exact exit (only with authentic exact data)
- [ ] Automatic provider contract-master expiry resolver
- [ ] Overnight historical pending reconciliation design
- [ ] Deferred Phase 7 five-strike historical selection comparison
- [ ] Risk Engine, manual-approved paper trading, controlled live trading
