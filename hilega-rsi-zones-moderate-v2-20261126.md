# Native Hilega update: RSI exit + EMA zones + moderate every entry

Updates the existing Hilega live-shadow and Historical Replay strategy in place. Strategy ID remains `HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT`; the new version is `rsi-two-route-1.1.0-3m-rsi-exit-ema-zones-moderate`. No separate workspace or service is added. Existing execution modes, lots, strike selection, `.env`, manual controls, order transport and append-only journals are retained. Historical replay caches use new source/version signatures; existing old evidence remains intact.

## Exact rules

Completed 3-minute bars and the existing 20 verified prior-session warmup. Wilder RSI5/9/14/21/28; WMA21 of RSI9; EMA30 High/Low plus EMA10 High/Low seeded from those same 3-minute bars.

CE: green candle and close > EMA30 High. PE: red candle and close < EMA30 Low. Normal Route: at least two of five RSI >55 CE / <45 PE, and WMA21(RSI9) >50 CE / <50 PE. WMA_bypass: all five directional RSI thresholds; WMA still available but its threshold is not required. Normal Route has priority.

Every prospective entry, including opposite entries and re-entries: valid positive-range candle, body >=50% of range, each wick <=body, CE upper wick <=20% of range or PE lower wick <=20% of range. New entries in either direction must close outside BOTH inclusive intervals: EMA10 High–EMA30 Low and EMA10 Low–EMA30 High. Each interval uses min/max of its two boundaries. Equality blocks. There is no next-candle confirmation requirement or inside-zone exception. These entry filters do not force existing trades to exit.

Exit on any applicable condition: (1) session end15:30, (2) fully qualified opposite entry (exit then reverse), (3) original fixed signal midpoint breach AND RSI5/9 opposite50, (4) original all-three momentum/WMA/opposite EMA30 boundary exit, or (5) standalone RSI5/9 opposite50. CE opposite50 means both <50; PE both >50. Strict inequalities. The reason priority matches the tested runner; the standalone RSI exit makes midpoint/WMA/price confirmation unnecessary once both RSI checks pass. No same-side re-entry on the RSI/midpoint exit candle.

No 09:30–15:15 entry restriction is added. Original 15:30 session-end handling remains. Research marks are next-minute OPEN, with exact15:29 CLOSE for session end. Broker fills remain governed by the existing execution pipeline.

## Validation

23 unit/integration/rollout tests; exact parity with the uploaded selected-configuration research across17 November sessions/84 trades, including events, fills, reasons, peaks and giveback. Frontend TypeScript/Vite build and full application import/HTTP route checks. The installer repeats staged tests and companion integrity checks with the VM's actual environment.

## Install on the VM

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -u -B hilega-rsi-zones-moderate-v2/manage.py --install
```

`--prepare` can build and test an isolated candidate while the existing strategy continues. `--install` prepares, then attempts a controlled cutover. The cutover requires flat native ownership, local basket/legacy/manual-exit ledgers, and observer positions/pending deliveries. It stops only importing API/analytics/reference/readiness components and an already-managed quote observer/basket worker, checks again while the source producer is stopped, installs backups and new source/pins/assets, restarts those same components, verifies the new API identity, and commits the activation boundary. Existing unrelated preparation/failed production-worker state is preserved.

An open trade blocks installation; the installer does not close it or change its rules mid-trade. If blocked after preparation, retain the printed stage and use `--apply --stage /tmp/hilega-rsi-native-...` after the original trade closes. A changed configuration/source lease requires a fresh preparation. New entries become eligible only for completed candles whose boundary is after the committed activation boundary; earlier reconstructed checks cannot open retroactive trades. No session arming or production-order enablement is performed by the installer.

A backup receipt is written under `data/recovery/hilega-rsi-native-install-.../receipt.json`. Failed cutover restores source/config/assets and original service state. Explicit rollback is `manage.py --rollback PATH/receipt.json`, guarded by flat state and source hashes. Old journals, trades and historical files are not deleted or relabelled. Preserve any failure logs; do not bypass hash or flat-state checks.

## Verify after success

```bash
curl -fsS 'http://127.0.0.1:8123/api/live-shadow/hilega-directional/status?fast=true' | .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({k:d.get(k) for k in ("active_strategy_id","strategy_version","current","worker_component_health")},indent=2))'
bash scripts/status_hilega_policy_observer.sh
```

Refresh existing Hilega Live Shadow and Historical Replay screens. A fresh historical calculation uses the updated strategy; live decisions remain activation-boundary gated. The install receipt and API response, rather than package preparation alone, establish whether the VM is updated.

## Installer revision2
Preserves the VM observer fix distinguishing candle checkpoint09:15–15:29 from availability timestamps09:16–15:30. The reviewed VM source SHA256 is e3153bffae16baa50c045104a69c5a8cbaa3ec1a36502f843051f970ed177233. Strategy version and trading rules are unchanged from revision1. No source-check bypass is added.
