# Persistent overall Sandbox P&L

Keep the armed-session P&L panel and add overall five-leg Sandbox totals across all retained sessions and strategies: closed estimated net, open estimate, total, gross gains/losses, gain/loss ratio, completed/partial baskets, missing-price count and date coverage. Completed historical baskets also become available in the date selector.

Totals are rebuilt from data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl. They survive browser refresh, API/VM restart, new-session arm and strategy selection while that journal is retained. No daily counter reset can erase history. Keep this directory on persistent disk and in backups; deletion of the journal cannot preserve evidence. No journal mutation or broker call occurs during installation. No trading behaviour, quantity, arm or gate changes. Older one-contract experiment journals are not mixed into five-leg totals.

Closed values use recorded entry/exit premium and actual recorded quantity; open values use current quotes when available. All amounts remain estimates, not confirmed fills. Missing prices are disclosed and totals are known-price subtotals. Closed aggregate is reconstructed identically after re-arm.

Install after the trade-date-filter bundle, extract in ~/RB-ITOS-AI, then:
```bash
source .venv/bin/activate
python hilega_sandbox_overall_pnl_bundle/install.py &&
./scripts/restart.sh
./scripts/status_hilega_upstox_sandbox_worker.sh
```
Refresh browser. Installer includes source guards and rollback. Nine tests passed including two-session gains/losses, future-session re-arm, fresh worker reload and completed-history retention; frontend build passed. No actual broker fill validation performed.
