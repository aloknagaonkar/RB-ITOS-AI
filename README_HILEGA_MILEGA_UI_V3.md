# Hilega-Milega Dashboard + Inline Audit V3

Applies on top of the previously installed Phase 7B and Hilega Live Shadow UI V2 code. Changes are limited to a read-only audit/dashboard projector, live API read endpoint and frontend presentation. Does not change worker, strategy, trading rules, option pricing, candidate selection or execution flags.

## Apply

From `~/RB-ITOS-AI`, extract ZIP to repository root **after reviewing the included changes**. This updates the existing backend API/audit projector, existing Hilega UI and CSS and adds one new read-only projector and two tests. Retain your existing worker config and `.env`. Do not copy the top-level README into frontend.

```bash
cd ~/RB-ITOS-AI
unzip -l /path/to/hilega_milega_dashboard_inline_audit_v3.zip
unzip -o /path/to/hilega_milega_dashboard_inline_audit_v3.zip -d .
source .venv/bin/activate
python -m pytest tests/test_hilega_milega_trade_dashboard_v1.py tests/test_hilega_milega_exit_audit_link_v1.py -v
python -m pytest tests/test_hilega_milega_audit_report_v1.py tests/test_hilega_milega_live_shadow_v1.py -v
cd frontend && npm run build
```

Then restart only the backend API service serving `/api/live-shadow/hilega-milega`. Restart or hot-reload frontend according to your deployment; **no Hilega worker restart required** as worker/strategy code is unchanged. Preserve existing append-only audit data.

## UI
- Top cards: strategy state, last entry, last exit, completed exact five-leg shadow lifecycles.
- Overview: per-moneyness **separate** cumulative realized CE premium points, positive trade count, mean return, counts of active and missing/incomplete observations. Five CE legs are hypothetical alternatives, not a single held five-leg position.
- Each trade: full ATM-2, ATM-1, ATM, ATM+1, ATM+2 entry/exit premium, entry/exit time, latest option premium, realized points and %, current premium move, MFE and MAE. Unavailable exact data displays dashes and data limitations, never invented P&L.
- Audit expands **under selected trade or event** (not right-side drawer), with existing RSI/EMA/WMA decision/route details plus CE lifecycle. An exit checkpoint now links back to the original strategy entry so exit-click audit includes entry and exit prices from the same five CE contracts.
- Total account rupee P&L deliberately unavailable: no quantity, transaction costs, bid/ask fill or actual execution. Underlying chart points kept distinct from option premium points.

## Verification
Implemented and locally run: 5 new Python unit tests passed; Python source compiles; TypeScript JSX parsed/transpiled with no syntax diagnostics. Full existing repo regression and frontend TypeScript typecheck/production build must be run in actual repo (dependencies not present in isolated workspace).

## Updated checklist
[x] Entry/exit overview UI
[x] Separate completed-trade premium points for each ATM±2 CE role
[x] Individual CE premium entry/exit and realized % in trade ledger and audit
[x] Inline expandable audit patterned after historical replay
[x] Exit audit links original entry lifecycle
[x] Fail-closed missing price displays, no synthetic P&L
[x] Worker and strategy unchanged; execution disabled
[ ] Verify on real live audit records that candidate→start→updates→exit all appear and dashboard aggregates match JSONL
[ ] Run full backend regression and `npm run build` on VM
[ ] Hard recorded-session live/historical event + dashboard diff
[ ] Naturally observe Route B and 14:55 five-leg exit
[ ] Automatic expiry resolver and persistent long-term trade ledger
[ ] Deferred ATM±2 historical comparative research
