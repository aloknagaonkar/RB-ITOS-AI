HILEGA WMA-GAP FORWARD CONFIRMATION V1

Purpose
- Preserve the frozen 490-session WMA-gap research artifact unchanged.
- Automatically publish later completed directional live sessions into a
  separate forward-confirmation report.
- Make those dates available in the existing Hilega Historical Replay UI.

Eligibility
- Recorded directional live audit contains DIRECTIONAL_SESSION_CUTOFF/PROCESSED.
- Exact cached NIFTY minute data is complete.
- Session is not part of the frozen report.
- Session has not already been published.

Storage
  data/historical-evidence/hilega-wma-gap-forward-confirmation-v1/
    report.json
    trade-results.csv
    confirmation-attempts.csv
    candidate-timeline.csv
    sessions/YYYY-MM-DD/  (immutable per-session evidence)

Install
  python hilega_wma_gap_forward_confirmation_bundle/install.py
  ./scripts/restart.sh

Manual status
  ./scripts/status_hilega_wma_gap_forward_publisher.sh

Safety: observation only; no strategy, audit, quantity or order mutation.
