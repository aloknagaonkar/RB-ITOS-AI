# Native Hilega RSI strategy replacement v2

This updates the existing Hilega Live Shadow and Historical Replay pipeline. It replaces `HILEGA_V2_ALIGNMENT_DUAL_EXIT` with `HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT` and policy version `rsi-two-route-1.0.0-3m-native-confirmed-midpoint`.

There is no new workspace, service, simulator or order transport. The separate RSI workspace registration and selectors from the previous bundle are removed. The existing Historical Replay strategy selector defaults to the new RSI policy. Historical data are recalculated into `data/historical-evidence/hilega-rsi-native-v1`; old research/live journals are retained.

## Rules retained from the audited baseline

Completed 3-minute candles, Wilder RSI5/9/14/21/28, WMA21 of RSI9, EMA30 High/Low, exactly 20 verified prior sessions.

| Entry | CE bullish | PE bearish |
| --- | --- | --- |
| Common | Green candle; close > EMA30 High | Red candle; close < EMA30 Low |
| Normal Route | At least 2 of 5 RSI >55 AND WMA21(RSI9) >50 | At least 2 of 5 RSI <45 AND WMA21(RSI9) <50 |
| WMA_bypass | All5 RSI >55; WMA threshold bypassed | All5 RSI <45; WMA threshold bypassed |

All indicators, including WMA, must be available. Normal Route has priority. No candle-strength, extra follow-up, time-window or trailing-stop requirement is added. Single owner; no pyramiding.

Exit priority:

1. Session end15:30 IST.
2. Fully qualified opposite entry: exit old direction first, then accept opposite.
3. Fixed original signal range midpoint `(high+low)/2`: CE close below midpoint AND RSI5<50 AND RSI9<50; PE close above midpoint AND RSI5>50 AND RSI9>50. Same completed candle; strict comparisons. No same-side re-entry on that midpoint-exit candle.
4. Original all-three exit: CE RSI5<50 AND RSI9<50 AND WMA21(RSI9)<50 AND close<EMA30 Low. PE mirrors >50 and close>EMA30 High.

NIFTY reference marks use the next minute open and exact15:29 close at session end. Option identity, candidate selection, sizing, expiry resolution, exact entry/exit evidence, pending-order reconciliation and provider fill-price accounting stay in the existing Hilega pipeline.

## Existing execution configuration

The reviewed VM has `FIVE_ACTUAL_SANDBOX_LEGS` in its basket control and `SIMULATION_ONLY` in its separate production-workspace setting. These are different settings. This update preserves both, along with kill switches, armed/session state and other execution controls. It preserves `.env` byte-for-byte, maps its approved legacy alignment setting to the new native strategy in code, and rebinds the existing basket control's strategy ID/version/policy while flat. It does not arm a session or enable production execution. An already-running basket worker resumes its original configured behavior after restart.

The active trade controls, manual exit/reset and the existing option/P&L cards are retained. The event bridge recognizes both old journal reversals and new RSI reversals; old events are never relabeled or rewritten. Version checks continue to reject stale entry intents. No changes to fill/cancel/submit algorithms or lots are included.

## Install

The package is based on the exact source review uploaded from the VM on25 November. Run from `~/RB-ITOS-AI`:

```bash
.venv/bin/python -u -B hilega-rsi-native-update-v2/manage.py --install
```

Preparation verifies exact source hashes, existing companion integrity, all native tests, the full application HTTP routes and TypeScript/Vite build. It writes an isolated `/tmp/hilega-rsi-native-...` stage, logs, `changes.diff` and `prepared.json`. It imports the staged API without entering its lifespan. It waits for the existing display cache's initial warming response; real cache errors remain failures.

The installer checks local basket, legacy and manual-exit ledgers. Any open legs, pending fills, uncertain requests, unresolved legacy requests or unfinished manual exit blocks the change. It does not submit a closing order to make an upgrade possible. These are local-ledger checks, not a new broker-account reconciliation.

Apply holds the same execution lock used by the existing basket/manual-exit worker. It preserves the native preparation worker and the failed production-source-worker states, reloads the API, lifecycle-reference companion, observation-analytics and observation-readiness services, and restarts an existing basket process only if it was already running. It creates no new trading service. A separate RSI worker must already be inactive.

Only currently reviewed strategy/routing settings are accepted. Unexpected source/config changes, an explicit systemd strategy override, or a ranked-strike policy needing a version review stops installation rather than silently changing authority or selection.

## Cutover and restart

During installation, the native activation record blocks entries until reload/health checks complete. It then chooses a completed3m cutover boundary. The first eligible live entry is from a full candle after that boundary. Previous candles remain auditable with a cutover blocker. Historical replay evaluates the complete session and does not apply the live cutover block.

On restart, recovered bars may restore an entry only if the same native version previously recorded a processed entry at that boundary. Recovery cannot create a new tradable entry from an old, unaudited signal. Existing audited option identities are restored using the original lifecycle restoration logic. Actual fills and manual reset evidence remain in their original ledgers.

## Verify

```bash
curl -fsS 'http://127.0.0.1:8123/api/live-shadow/hilega-directional/status?fast=true' \
  | .venv/bin/python -m json.tool

journalctl --user -u hilega-observation-analytics.service -n 40 --no-pager
```

Expected active ID: `HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT`.
Expected policy version: `rsi-two-route-1.0.0-3m-native-confirmed-midpoint`.

Refresh the usual Hilega page. Existing Live Shadow and Historical Replay tabs remain. The native decision audit shows both directions, each RSI gate and vote count, WMA, candle colour, EMA30 position, route blockers and exit checks. Open/closed option trade cards and manual controls stay on that screen.

Historical Replay defaults to the new RSI strategy through the same `V2_ALIGN` API selection key. Use Local candle cache inputs. Old validated research is not reused as proof for the new policy. Dates with underlying caches are listed independently of whether a new replay has already been generated. Current-session readiness still depends on valid candles/warmup and current worker health; a service being active alone is not a readiness guarantee.

## Rollback

Apply prints a private backup receipt under `data/recovery/hilega-rsi-native-install-.../receipt.json`. It backs up sources, companion anchors, frontend assets and the original settings. The approved `.env` is not edited or copied into the update backup; its hash is checked before and after installation.

```bash
.venv/bin/python -u -B hilega-rsi-native-update-v2/manage.py \
  --rollback data/recovery/hilega-rsi-native-install-REPLACE/receipt.json
```

Rollback requires flat local ledgers, refuses post-install file edits, restores the old configuration and code, and reloads the same services. All original journals, new audit records and research evidence are retained. The separate RSI worker is not re-enabled.

## Validation

See `validation.json`. Native historical replay matches all169 baseline trades over36 sessions. October was independently reseeded from supplied raw candles; November uses supplied indicator frames. All20 October sessions also match through the real native live coordinator's option callbacks. Mocked original CE/PE lifecycles open/close all5 legs at the correct3m boundary. Unit tests cover entry/exit rules, manual owner release, legacy/new reversal bridge order, stale version rejection, cutover/recovery, flat guards, API cache warming and rollback.

The frontend TypeScript/Vite build passed locally. Two unchanged `.mjs`/declaration build inputs and `index.html`, omitted by the source exporter, were taken from the prior source snapshot for that local build; the VM preparation must rebuild against its actual full frontend. No broker order submission or option profitability is claimed by these tests.

## V2 supervisor compatibility

The VM supervisor pins the exact approved `.env` bytes. V2 leaves that file untouched and resolves `HILEGA_V2_ALIGNMENT_DUAL_EXIT` to the promoted native RSI ID at the existing runtime/API/execution configuration boundaries. Recorded journal IDs are not mapped, so old trades and new trades remain distinct. No environment approval, supervisor check, execution mode or credentials are changed. Native API status reports both the configured ID and effective active ID. The health check writes a bounded diagnostic before automatic rollback.
