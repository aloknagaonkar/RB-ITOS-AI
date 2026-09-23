# Unified Hilega-Milega historical replay and live-shadow decision tables

This frontend-only patch adds one shared canonical-audit presentation component to
BOTH the existing Historical Replay → Hilega panel and the Hilega Shadow Live page.
No strategy rules, market adapters, backend routes, broker calls, live worker,
execution permissions or immutable evidence are modified.

## Changes

- The original ALL3 Historical Replay page is preserved. Hilega retains its own
  session and capture selectors; `d4` on 2026-09-23 is the first test capture.
- The Hilega historical panel uses a primary five-column checkpoint table:
  Time IST | Strategy decision | Opening/Route A/Route B | Signal detected | Audit.
- Each row has colored DETECTED/ENTRY/EXIT/ACTIVE/REJECTED statuses and
  expandable audit cards, recorded condition matrix, candidate records and CE
  premium analysis; filters simplify review.
- Entry/exit audits show independent ATM±2 CE entry/exit time and OPEN premiums,
  premium-point P&L, P&L %, MFE, MAE where present; missing exact prices stay
  unavailable. No rupee/account profit is inferred.
- Historical mode offers **Full-session table** for retrospective inspection or
  **Candle-by-candle mode** for progressive review. Progressive review restricts
  future checkpoints and, where event timestamps prove availability, linked CE
  updates/results; otherwise linked details remain unavailable until full review.
- Historical manual notes stay in browser localStorage using the prior
  `hime-review:<capture_id>` key and can be exported as JSON. Audits are immutable.
- Hilega Shadow Live continues polling its existing API and ledger. It displays
  every available audited decision checkpoint in the SAME five-column table;
  opening an audit retrieves full detail and refreshes it every five seconds.
- No existing live shadow service restart is required; the app serves
  `frontend/dist` directly once the frontend build completes.

**Important scope:** This patch LOADS completed Hilega historical captures. It does
not introduce a new broker-download/replay job endpoint. The existing ALL3
Run Replay action must NOT be mistaken for a Hilega replay runner.

## Compatibility

Based on the user-supplied repository ZIP and the subsequently installed
independent-Hilega-session component (`hilega-independent-session-selector-fix`).
The installer recognizes the exact existing historical component version and
existing live page activity-table anchor, and refuses unknown modifications.
It also accepts either parent invocation, with or without the obsolete date prop.

## Install on VM (after transferring ZIP)

```bash
unzip hilega-unified-decision-tables-patch.zip -d /tmp/
cd ~/RB-ITOS-AI
source .venv/bin/activate
python /tmp/hilega-unified-table-patch/install.py --repo "$PWD" --check
python /tmp/hilega-unified-table-patch/install.py --repo "$PWD" --apply
node tests/test_hilega_decision_table_v1.cjs
cd frontend && npm run build
```

Only run `--apply` if `--check` passes. If it says BLOCKED, paste the output;
do not overwrite files manually. The patch backs up each modified existing
source file beneath `.hilega-unified-table-backup/<timestamp>/` and is
idempotent if run again unchanged.

After the frontend build, Ctrl+Shift+R in the browser. No `scripts/restart.sh`
or live-shadow/API restart is required. Your live worker and its evidence file
stay running with the existing journal lock.

## Validation performed before packaging

- Safe installer tested against a simulation of the documented independently
  selectable historical component plus the uploaded Hilega live component.
- Installer `--check`, `--apply`, and repeat `--check` passed.
- Shared classification/P&L contract tests passed locally.
- TypeScript TSX syntax transpilation succeeded for the new components and
  changed integration points.

**Not verified here:** VM production build, browser rendering, and actual d4
or next-day live data display. Run `npm run build` on the VM and check both
pages against their actual audit records. This is NOT proof of historical/live
market-data parity or of trading profitability.

## Smoke-test acceptance

1. Existing ALL3 Historical Replay still works.
2. Hilega Historical Replay → select 2026-09-23 → d4 → Load existing replay.
   Verify checkpoint count and audited times, including opening path, Route A/B,
   entries and exits where supported by the capture.
3. Click entry/exit Audit and compare candidate five CE rows and exact observed
   entry/exit minute opens with JSON source evidence. Verify missing premiums
   show unavailable rather than 0 or substituted values.
4. Switch to candle-by-candle mode and verify the future rows and future exit
   premium results are hidden until the corresponding candle completes.
5. Hilega Shadow Live → inspect its decision table while leaving its existing
   premium ledger and safety status intact. Check yellow detected, green entry,
   red exit and expandable details on real audit events.
6. Confirm the live-shadow PID and `.env` are unchanged.
