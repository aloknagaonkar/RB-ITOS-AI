MIDPOINT HISTORICAL HEALTH DEDUPLICATION
=========================================

Place this folder directly under the RB-ITOS-AI repository root and run:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_historical_health_dedupe_bundle/install.py

Then rebuild only the October 1 overlay:

  PYTHONPATH=backend:. python scripts/materialize_midpoint_historical_health.py \
    --dates 2026-10-01 --force

The immutable replay audit is authoritative.  Reconstructed historical health
is written only for observations absent from that audit.  No strategy event,
entry, exit, order, quantity, service, or worker is changed.

