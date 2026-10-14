# Hilega / Midpoint session recovery

Revision 3: restores the complete supplied stale-session status contract:
`current.session_date`, `current.state_available`, and
`latest_state_session_date`. Yesterday's saved data remains accessible, but
its lock is never treated as today's active state. The fixed-date regression
checks all supplied backend assertions. Local installer-selected suite:
37 tests passed. Your VM has additional tests; those remain untouched.

Based on the supplied repository ZIP, commit d0e6de4d492a751bcf447ca020c87a8b4449d500.

## Findings

The supplied log shows incomplete historical warmup 15:25 (15:29 missing), raising before Hilega bootstrap completes. The shared worker runs Hilega before Midpoint without isolation, so that exception prevents Midpoint processing too. The UI exposes yesterday's locked state as current. No evidence shows sandbox caused the lock. The patch does not modify sandbox dispatch or strategy rules.

## Changes

- Validate full warmup sessions. Refetch invalid caches, validate before replacement, preserve old bytes in a dated sibling backup. No fabricated candle or shortened warmup.
- Isolate market-evidence, Hilega and Midpoint tick failures. Retry failed components after 30 seconds. Log exception type only; latest component health is exposed in directional status.
- Current Hilega UI state uses today's IST session only; show explicit readiness/warning rather than stale SESSION_LOCKED.
- Midpoint event timeline keeps original audit order. Health remains projected into columns; synthetic market-health minute rows no longer flood the event stream. Raw audit files are unchanged.
- Separate historical NIFTY recovery command; strict 375-minute / 75-bar coverage. Never submits orders.

## Install on VM

Unzip this bundle inside RB-ITOS-AI. Stop the shadow worker with your existing service procedure before installation. Do not run downloads during live processing.

```bash
source .venv/bin/activate
python hilega_midpoint_session_recovery_bundle/install.py
./scripts/restart.sh
./scripts/status.sh
```

Installer backs up source and rolls it back on failed tests/build. It does not start, arm, disarm or dispatch sandbox orders.

## Recover October 6 and 7

```bash
PYTHONPATH=backend:. python scripts/recover_shadow_market_dates.py --dates 2026-10-06 2026-10-07
PYTHONPATH=backend:. python scripts/materialize_midpoint_forward_market_data.py --dates 2026-10-06 2026-10-07 --broker-only --output-root data/recovery/october-2026/midpoint
```

These commands use your configured analytics access, never display tokens, and write separate recovery data. The existing Midpoint downloader acquires paired NIFTY/futures data with its strict strategy-window validation. Broker availability/permission failures remain blockers. Do not copy recovered data into immutable recorded-live journals.

## Validate after restart

```bash
curl -fsS http://127.0.0.1:8123/api/live-shadow/hilega-directional/status -o /tmp/hilega-status.json
python -m json.tool /tmp/hilega-status.json
tail -50 data/live-shadow-worker.log
```

Check current_session_date, current_session_ready, session_warning and worker_component_health. During a completed session with market data available, today's bootstrap and last bar must advance. A failure must show the component error while other strategies keep processing. Component health has a timestamp: an old OK is not current evidence.

## Validation checklist / remaining work

- [x] Local regression tests for incomplete-cache repair and fail-closed replacement.
- [x] Local regression test: Hilega failure does not prevent Midpoint callback.
- [x] Event timeline regression: no synthetic minutes; decision order retained.
- [x] Existing bootstrap, evidence, health and UI tests.
- [x] Local TypeScript/Vite production build passed after installing locked dependencies.
- [ ] Run installer tests/build again on VM.
- [ ] Download Oct 6 and Oct 7 on VM and inspect coverage output.
- [ ] Replay downloaded evidence with explicit historical-recovery provenance.
- [ ] Compare each date's recorded signals versus independent replay, including missing/unresolved entries. Do not classify a worker outage as zero-signal success.
- [ ] Confirm a subsequent live session bootstraps and both strategies emit events.

Oct 6/7 downloads and replay results are NOT claimed complete in this bundle. Credentials and VM access are not available in the analysis workspace. A historical reconstruction cannot recover actual missed live decisions. Frozen 490 evidence and existing live audit/order files remain untouched.
