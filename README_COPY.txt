CONTROL FAILURE FROZEN 36 VALIDATION V6.1
=========================================

Fix:
- Historical build return codes no longer crash the 36-day runner.
- A PARTIAL/FAILED historical date is reported and the runner continues.
- Existing frozen V5 theory remains unchanged.

Test:
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_validate_control_failure_frozen_36_v6.py -v

Run:
python scripts/validate_control_failure_frozen_36_v6.py --build-missing

For a date returning rc=2, inspect:
cat data/historical-evidence/historical-oi-build/<DATE>/build-status.json
tail -n 120 data/historical-evidence/historical-oi-build/<DATE>/build.log

For the observed case:
cat data/historical-evidence/historical-oi-build/2026-08-24/build-status.json
tail -n 120 data/historical-evidence/historical-oi-build/2026-08-24/build.log
