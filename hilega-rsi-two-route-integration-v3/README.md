# RSI Two Route — Confirmed Midpoint integration v3

New strategy `HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT`, version `1.0.0`.
Research policy reference: `rsi-two-route-0.5.1-confirmed-midpoint-research`.

This package adds historical replay and an independent Hilega live-shadow simulation worker. It adds a strategy selector to the existing Hilega Live Shadow and Historical Replay screens. The existing strategy remains the default selection. Select **RSI Two Route — Confirmed Midpoint · simulation** to open the new audit workspace.

## Exact rules

Use completed 3-minute candles and exactly 20 verified prior sessions. Wilder RSI on closes: 5, 9, 14, 21, 28. WMA21 of RSI9. EMA30 calculated separately on candle highs and lows.

| Gate | CE / bullish | PE / bearish |
| --- | --- | --- |
| Common price | close > EMA30 High | close < EMA30 Low |
| Common colour | close > open | close < open |
| Normal Route | at least 2 of 5 RSI > 55 AND WMA21(RSI9) > 50 | at least 2 of 5 RSI < 45 AND WMA21(RSI9) < 50 |
| WMA_bypass | all 5 RSI > 55; WMA threshold bypassed | all 5 RSI < 45; WMA threshold bypassed |

All indicators, including WMA, must be available. Normal Route has priority. Single owner, no pyramiding. Candle strength is diagnostic only. No additional candle-strength, whole-candle/follow-up or first/last-15-minute entry filter is enabled in this audited baseline.

Any exit below closes the position, in this priority order:

1. Session close at 15:30 IST.
2. Fully qualified opposite entry: close existing and open opposite at the same modeled boundary mark.
3. Fixed **original signal candle range midpoint** `(high + low)/2`: CE close below midpoint AND RSI5 < 50 AND RSI9 < 50; PE close above midpoint AND RSI5 > 50 AND RSI9 > 50. All conditions must hold on the same completed candle. Equality/wick-only breach does not count. No same-side re-entry on that exit candle.
4. Original ALL_THREE exit: CE RSI5 < 50 AND RSI9 < 50 AND WMA21(RSI9) < 50 AND close < EMA30 Low. PE mirrors with >50 and close > EMA30 High.

## What gets installed

- New Python package `backend/market_lab/hilega_rsi_two_route_v1/` with one incremental engine shared by historical and live adapters.
- One additive router import/registration in the current VM's `backend/market_lab/api.py`.
- Additive selectors around the current `hilegaMilegaShadow.tsx` and `hilegaHistoricalReplay.tsx`; new iframe component and server-rendered audit workspace.
- Rebuilt frontend assets; existing hashed assets are retained. The new index is installed last.
- Current companion runtime manifest and its two hash anchors are reissued for exactly the changed/new Python files, while retaining closed execution authority.
- New user service `hilega-rsi-two-route-shadow.service`. Existing strategy workers, their state and their services are not changed or restarted.

Only the existing API and lifecycle-reference companion are restarted. No `.env` changes or broker orders. No existing strategy positions are closed or adopted. All new simulated trades belong to the new strategy.

## Installation on the VM

For the authorized rollout, this runs preparation and all checks, then installs automatically **only if every check passes**:

```bash
.venv/bin/python -u -B hilega-rsi-two-route-integration-v3/manage.py --install
```

Preparation and apply can also be run separately as below. The prepared stage includes `changes.diff`, build/check logs and exact before/after file hashes.

From the repository root, extract the package and run:

```bash
.venv/bin/python -u -B hilega-rsi-two-route-integration-v3/manage.py --prepare
```

Preparation prints the exact `/tmp/hilega-rsi-integration-...` stage path. It reads the current VM files, checks unique source anchors, validates the current companion, stages all changes, validates the updated companion, runs the integration tests and complete application import, checks the audit JavaScript, then runs the VM's full TypeScript/Vite build. No installed sources or services are changed by preparation. A lock file under `data/recovery` is used.

If it prints `PREPARED_NOT_INSTALLED`, use the exact printed stage:

```bash
.venv/bin/python -u -B hilega-rsi-two-route-integration-v3/manage.py \
  --apply --stage /tmp/hilega-rsi-integration-REPLACE_WITH_PRINTED_STAGE
```

Apply refuses changed source hashes, changed staged files, a different package, or an already-existing new worker service. It saves a rollback receipt under `data/recovery/hilega-rsi-install-.../receipt.json`, installs the reviewed candidate, restarts API/reference, checks the API, and enables the independent simulation worker. It attempts rollback on installation failure.

Then check:

```bash
systemctl --user status hilega-rsi-two-route-shadow.service --no-pager
journalctl --user -u hilega-rsi-two-route-shadow.service -n 30 --no-pager
curl -fsS http://127.0.0.1:8123/api/live-shadow/hilega-rsi-two-route/live
```

Refresh the browser, choose the new strategy, and verify both directions' audit rows. A running service alone does not establish data readiness: inspect the endpoint's `health`, observation age and last completed bar. Missing/invalid candles, seed changes, source revisions, and unknown calendar years block processing explicitly.

The installer has no intraday cutoff restriction. It preserves the existing workers; the API restart may briefly interrupt UI requests.

## Populate historical replay

After installation, recover only missing/invalid inputs into this strategy's own cache and run the same engine:

```bash
PYTHONPATH=backend .venv/bin/python -u -B \
  -m market_lab.hilega_rsi_two_route_v1.cli --repo "$PWD" \
  --from 2026-10-01 --through 2026-11-23 --recover-missing
```

This uses the existing Upstox candle reader; it does not construct an order transport. It never replaces the original caches. Every saved replay is keyed by strategy/version, code hash, target candle hash and all 20 seed-session hashes. Session discovery comes from candle coverage and reviewed calendar, independently of legacy replay exports. Missing data returns a visible blocked reason, not a legacy result or misleading 404.

The reviewed calendar covers 2026 only. The special 8 November session keeps the existing 09:15-anchored grid: drop the incomplete 14:20 minute and use 23 complete buckets from 14:21 through 15:30. This preserves the audited baseline; it is not a claim about independently reverified exchange schedules.

## Live provenance and storage

All new writes: `data/historical-evidence/hilega-rsi-two-route-v1/`.

- `inputs/`: strategy-owned recovered candles.
- `replay/<date>/<content-key>.json`: independent results.
- `live.sqlite3`: durable atomic state, completed candle tape, audits and health.
- `worker.lock`: process lock.

Signals use only completed 3-minute OHLC. Entry/exit reference marks use the next 1-minute open; terminal close uses exact 15:29 close. A missing next open yields `PENDING_REFERENCE_OPEN`. Forming-minute high/low/close never affect decisions. Each live audit records logical boundary, actual observation time, latency, recovered flag and modeled mark basis. Bootstrap/recovery events are not represented as executed orders. Source revisions to committed data or used marks fail closed.

Open P&L, peak and giveback use completed 3-minute frames and show their as-of boundary. Closed extrema use all held minute candles. Sum of trade peaks is not a simultaneously attainable account P&L. These are NIFTY modeled points; option premiums, costs and slippage are not validated.

Restart restores the new strategy's private state. Interrupted prior-day simulations are finalized from exact historical inputs before the next day is processed. Failure to obtain those inputs blocks recovery explicitly; no overnight owner is silently treated as flat.

## Audit UI and exports

Filters: date range, session date, CE/PE, route, all/event/blocked candles. Every completed candle includes checks, actual values, required values, RSI vote count, both route blockers, owner before/after, accepted events and exit conditions. Trades include signal/entry/exit time, reference prices, net, peak, giveback and exit reason. Active owner is separate from new-signal status. CSV and filtered standalone HTML downloads are included; the HTML shows which date and filters produced it.

Direct workspace: `/api/live-shadow/hilega-rsi-two-route/workspace?mode=historical` or `mode=live`.

## Rollback

Use the exact receipt printed by apply:

```bash
.venv/bin/python -u -B hilega-rsi-two-route-integration-v3/manage.py \
  --rollback data/recovery/hilega-rsi-install-REPLACE/receipt.json
```

Rollback stops/removes only the new worker, restores changed sources, companion pins and frontend files, and restarts API/reference. It refuses to overwrite post-install edits. New simulation journals and historical evidence are retained.

## Validation included

See `validation.json` for local checks and their limits. Regression: all 169 audited trades and 36 sessions match; October is independently recomputed/reseeded from supplied raw candles, November uses supplied completed indicator frames. Full installed-application import, VM source/companion checks and complete frontend build must pass during `--prepare`. Rendered browser review and actual VM worker readiness follow installation. No claim of broker execution validation is made.

## Installer v2 correction

The v1 preparation rejected the audit HTML as a non-Python runtime pin. V2 explicitly allows that one packaged HTML asset, retains its installation hash lease, pins every Python module, and continues rejecting unexpected backend assets and unsafe paths. Strategy rules and engine files are unchanged. The v1 failure occurred before staging installation or service changes.

## Installer v3 API check

The installed FastAPI can represent included routers with deferred objects that do not have a `.path` attribute. V3 verifies the rules and HTML workspace using in-process HTTP requests to the full staged application. The check intentionally does not enter the application lifespan, start workers, or invoke replay/live endpoints. Missing routes, incorrect strategy identity/version/mode, and incorrect workspace responses still block installation. Strategy and UI payloads are unchanged.
