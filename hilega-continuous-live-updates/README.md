# Hilega continuous display updates and active live estimates

This patch changes display polling and adds an observation quote bridge. It does not change setup, signal, follow-up, entry/exit, cutoff, option ranking formulas, execution controls, sandbox orders, fills or historical results. The installer verifies the protected strategy/order modules have identical hashes before/after applying.

## Implemented

| Area | Update |
|---|---|
| Active candle trade dashboard | Poll every 5 seconds after the preceding request completes |
| Decision candles / entry checks | Independent 5-second polls; a status or trade request cannot block them |
| Status | Independent 10-second poll |
| Active live marks | Poll every 2 seconds after completion; publisher exports current cache about once per second |
| Open trade audit details | Refresh every 10 seconds while opened |
| Requests | Abort bounded requests, including stalled response bodies; retain prior values; retry; refresh on tab visibility/focus |
| New price/P&L columns | LTP, best bid, indicative points/one-lot estimate, bid exit estimate, quote timestamp/age; total only with all required leg evidence |
| Quote source | Existing publisher's Upstox streaming connection; no new broker connection or order call |

Live LTP is an indicative last-trade price, not proof of a fresh execution. Best bid is an estimated sell price; whole-lot exit estimate requires displayed bid quantity >= lot size. Rupee estimates require verified contract/expiry/lot metadata from the existing publisher catalog. Missing lot metadata leaves points available but rupees unavailable. No lot size is assumed. Fees/slippage excluded. No estimate is a fill.

The current completed-minute price/P&L columns remain available. New quote values are display-only, expire after 10 seconds, and are withheld on disconnected feed, stale snapshot, future timestamp, expiry mismatch or invalid book. They never write back into candle evidence. Closed trades retain original results. Browser polling is not guaranteed tick-by-tick; provider frequency and request duration affect latency.

## Compatibility

The accessible uploaded source is RB-ITOS-AI-updates_latest.zip. The installed VM also contains promotion/audit patches. Therefore the installer applies narrowly matched source transformations to current files instead of replacing whole files from the older ZIP. Matching was reviewed against both the supplied snapshot and promoted source. It stops on differing anchors; do not force it. Existing policy IDs/versions and unrelated changes are preserved.

## VM commands

No Python/project tests or frontend build were run in the assistant environment, per your preference. Download this ZIP to ~/RB-ITOS-AI:

```bash
cd ~/RB-ITOS-AI
(
set -e
unzip hilega-continuous-live-updates.zip
.venv/bin/python hilega-continuous-live-updates/install.py
.venv/bin/python hilega-continuous-live-updates/install.py --apply
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  tests/test_hilega_active_live_marks_v1.py \
  tests/test_hilega_combined_promotion.py \
  tests/test_hilega_execution_dispatch_validation.py
node tests/hilega_live_polling_vm.cjs
npm --prefix frontend run build
)
```

If all checks pass, load the API/observer changes:

```bash
cd ~/RB-ITOS-AI
(
set -e
bash scripts/restart_hilega_ui_api_safe.sh
bash scripts/stop_hilega_policy_observer.sh
bash scripts/start_hilega_policy_observer.sh
bash scripts/status_hilega_policy_observer.sh
)
```

The safe API restart handles a stale managed PID and refuses an occupied unverified port; it checks the strategy worker PID is unchanged. Restarting the separate read-only policy observer briefly reconnects its quote feed; its existing persisted observations resume. No live-shadow strategy worker restart or sandbox rearm is required.

Refresh the browser once with Ctrl+Shift+R to load the new JavaScript. Thereafter the page updates automatically. Quote requests are generated when the active panels are viewed, expire after 30 seconds, and are limited to current-day active observed contracts. Existing policy-observer subscriptions remain intact. If the observer has missing configuration or no streaming connection, live columns show unavailable; normal candle updates still work. The patch does not bypass that configuration gate.

## Read-only checks

With an active trade and the page open:

```bash
curl -sS http://127.0.0.1:8123/api/live-shadow/hilega-directional/active-live-marks \
  | .venv/bin/python -m json.tool
```

Check model HILEGA_ACTIVE_LIVE_MARKS_V1, stream_connected, per-leg status, quote age and lot metadata. Initial subscription/tick acquisition can take a few seconds. Empty quotes means there is no matching current-day ACTIVE observation. If estimates are unavailable, use these diagnostics instead of relaxing freshness rules:

```bash
bash scripts/status_hilega_policy_observer.sh
tail -n 40 data/logs/api-error.log
```

Manual validation: leave the page open through a completed 5m boundary and verify the decision candle arrives without reload; change tabs and return to verify immediate refresh; confirm live marks change while the old completed-minute column changes only with candle evidence; verify closed trades keep original exit results. Capture /active-live-marks output and test/build results if any part fails.

## Files and state

Edited existing files: frontend/src/hilegaMilegaShadow.tsx, frontend/src/hilegaIndependentObservations.tsx, backend/market_lab/hilega_directional_live_shadow_ui_v1.py, hilega_policy_live/publisher.py. New helpers/tests and safe API restart script are listed in the installer output. Timestamped backups are stored under backups/hilega-live-refresh-*. Display state is limited to active-mark-requests.json and active-live-quotes.json in data/live-observation/hilega-strike-observation-v1, plus installer receipt under data/runtime. No strategy audit journal or sandbox control is rewritten.
