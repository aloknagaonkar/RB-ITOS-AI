# Hilega-Milega Historical Replay add-on (existing UI)

This additive patch mounts a read-only historical Hilega panel on your EXISTING Historical Replay page and exposes two API endpoints to read prior Phase 7D captures.

## Notes about uploaded ZIP

The supplied source ZIP lacks the actual Sep 23 `data/historical-evidence/hilega-phase7d-2026-09-23-d4` capture and appears older than your installed Phase 7D.3 VM files: its historical capture CLI does not yet expose `--record-input-evidence`. Do not replace your live worker or other existing repo files with source extracted from that ZIP. Only use this additive patch.

## Install on VM

1. Copy/extract this patch ZIP to your VM (outside the repo or to a temporary directory).
2. `cd ~/RB-ITOS-AI`
3. `python /path/to/patch/install.py --repo "$PWD" --check`
4. If check passes, back up or commit any uncommitted changes, then:
   `python /path/to/patch/install.py --repo "$PWD" --apply`
5. `PYTHONPATH=backend python -m pytest tests/test_hilega_historical_ui_api_v1.py -q`
6. `cd frontend && npm run build`
7. Confirm that your September 23 evidence exists under `data/historical-evidence/hilega-phase7d-2026-09-23-d4`.
8. Deploy API/frontend by your normal procedure **only after** tests and build pass, taking care to avoid any unnecessary live-shadow worker restarts.

## What this patch does NOT do

- Does not rerun historical broker acquisition or modify captured files.
- Does not assert real-time/historical parity, especially given earlier 11 close mismatches.
- Does not read one-minute source tapes to draw an independent 1-minute chart; displays 5-minute OHLC from verified recorded audits only.
- Does not implement a new strategy or modify the original Historical Replay job runner.
- Does not send orders, touch credentials or restart your VM services.
- This first panel is historical review only. A broker chart overlay or same-input replay comparison requires verified persisted market-source tapes and a later additive step.
