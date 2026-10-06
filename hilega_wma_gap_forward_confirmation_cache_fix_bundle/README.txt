HILEGA WMA-GAP FORWARD CONFIRMATION — RECORDED CACHE FIX

Fixes the NOOP where completed live sessions were detected but not published.

Changes
- Materializes replay cache from immutable directional one-minute evidence.
- Requires exactly 75 complete five-minute bars before publication.
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
