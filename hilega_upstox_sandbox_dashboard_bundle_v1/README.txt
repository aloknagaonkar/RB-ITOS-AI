HILEGA UPSTOX SANDBOX DASHBOARD V1

Adds a read-only dashboard to the existing Hilega live page:
- active/armed strategy identity and mismatch protection
- worker, arming, kill-switch and order-cap status
- continuous quote-based open, closed and overall estimated P&L
- current active trade with signal/submission timestamps
- completed entry/exit ledger and broker order IDs
- blocked/failed event diagnostics

Safety:
- Upstox Sandbox only
- live execution remains disabled
- existing Hilega strategy rules are unchanged
- estimated P&L is explicitly separated from broker-realized P&L

Install:
  python hilega_upstox_sandbox_dashboard_bundle/install.py
  ./scripts/restart.sh

The installer backs up every changed target and restores it if validation fails.
