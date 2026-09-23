PHASE 7D.1: SINGLE-ZIP SAFE PATCH
================================

Upload this ONE zip to your Google Cloud VM home directory, then:

  cd ~
  unzip hilega-phase7d1-single-patch.zip -d phase7d1-single-patch
  cd ~/RB-ITOS-AI
  git branch --show-current
  git status --short
  python ~/phase7d1-single-patch/apply_phase7d1.py --repo ~/RB-ITOS-AI

If dry-run shows READY / ALREADY_PATCHED and NO CONFLICT, apply:

  python ~/phase7d1-single-patch/apply_phase7d1.py --repo ~/RB-ITOS-AI --apply

Then validate:

  source .venv/bin/activate
  git diff --check
  PYTHONPATH=backend python -m pytest -q \
    tests/test_hilega_phase7d1_acquisition_v1.py \
    tests/test_hilega_milega_functional_parity_replay_v1.py \
    tests/test_hilega_milega_real_session_parity_v1.py \
    tests/test_hilega_milega_phase7c_pending_exit_v1.py \
    tests/test_hilega_milega_live_shadow_v1.py

  PYTHONPATH=backend python -m market_lab.hilega_milega_phase7d_historical_capture_v1 \
    --session-date 2026-09-23 --expiry 2026-09-29 \
    --output-root data/historical-evidence/hilega-phase7d-2026-09-23-d3

This installer checks the exact source hashes from your supplied archive and
refuses to overwrite mismatches. Do not force it if conflicts occur.
It does not restart the worker or submit broker orders.
The intraday source cannot be used to recover a prior session.
