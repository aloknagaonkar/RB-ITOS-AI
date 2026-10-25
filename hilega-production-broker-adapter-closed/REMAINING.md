# Remaining gates after this package

1. VM tests/demo and read-only baseline for this adapter.
2. Integrate behind the installed controller's closed production gate: authoritative
   control version/session, fresh signals/health, verified contract/quote and cash
   reservation BEFORE transport, persisted reservation/intent linkage, and exit-only
   management while new entries are paused.
3. Connect receipts and actual order/trade/position evidence to the ownership ledger.
   Broker-side unknown acceptance cannot be solved by blindly retrying or importing
   an arbitrary ID. Define reviewed recovery evidence and escalation.
4. Complete partial-entry cancellation/cleanup, pending SELL behavior and direct
   Upstox partial/full exits. Do not oversell or infer flat from missing rows.
5. Verify real cash debit/reflection accounting, fees/buffer and 50% budget. Current
   NO_CASH_CAPACITY remains a blocker. No deposit is needed for offline testing.
6. Set the daily loss limit and final one-lot/ATM/risk configuration. Test current
   market/feed/quote evidence in market hours without automatic activation.
7. Deploy and test pre-market readiness, operational alerts, supervision, stale-feed
   entry pause, restart recovery and backup/rollback. Browser refresh is not control.
8. Explicitly authorize a supervised pilot only after required controls are proven.
   Separate the gate-opening change from this standalone package. Verify real fills,
   app/manual/direct-broker exits and cash/P&L before increasing lots or strikes.

Existing reference monitoring: 08:45 host/DB/clock; 08:50 warmup/bootstrap; 09:00
identity/broker/cash reconciliation; 09:05 contract/quote/feed; 09:10 readiness and
alerts; recheck before each entry. Continuous order/position/cash/control/heartbeat
monitoring is required. These production automations remain pending. The tested
simulator watchdog does not establish live broker-fault handling.
