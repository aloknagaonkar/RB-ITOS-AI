Midpoint M2.5 discovery bundle
===============================

This is intentionally read-only.

Why discovery first?
--------------------
M2.5 needs exact CE/PE instrument keys, premiums, MFE and MAE. The repository
already appears to contain Hilega option-observation logic, so we should reuse
the canonical provider/data path instead of inventing a second selector.

It also captures the new top-of-page requirement:
- trading/session date
- latest market-data timestamp
- latest audit timestamp
- last UI refresh timestamp
- freshness/data age
- source/mode

Run from ~/RB-ITOS-AI:
  source .venv/bin/activate
  export PYTHONPATH=backend
  python scripts/discover_midpoint_m25.py

It writes:
  /tmp/midpoint-m25-discovery.txt

No services are restarted and no repository files are modified.
