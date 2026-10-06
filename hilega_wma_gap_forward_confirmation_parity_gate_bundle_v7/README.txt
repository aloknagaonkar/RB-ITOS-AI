HILEGA WMA-GAP FORWARD CONFIRMATION — RECORDED CACHE FIX

Fixes the NOOP where completed live sessions were detected but not published.

Changes
- Materializes replay cache from immutable directional one-minute evidence.
- For forward sessions, requires the complete 69-bar strategy window through
  the locked 14:55 cutoff; missing post-cutoff candles never get fabricated.
- Uses report.sessions.last_session as the frozen 490-session cutoff.
- Produces short date-specific cache blockers instead of a global exclusion dump.
- Writes only the separate immutable forward-confirmation report.

Install and run
  python hilega_wma_gap_forward_confirmation_cache_fix_bundle/install.py
  PYTHONPATH=backend:. python scripts/hilega_wma_gap_forward_publisher.py --once

Restart the background publisher
  ./scripts/stop_hilega_wma_gap_forward_publisher.sh
  ./scripts/start_hilega_wma_gap_forward_publisher.sh
  ./scripts/status_hilega_wma_gap_forward_publisher.sh

Safety: observation only. Frozen evidence, live strategy, audit, sandbox worker,
quantity and orders are untouched.

Parity gate
- Compares recorded-live signal/completion counts with canonical replay.
- Marks mismatches PARITY_MISMATCH and forward_confirmation_eligible=false.
- Returns recorded-live entry timestamp, direction and event details for diagnosis.
