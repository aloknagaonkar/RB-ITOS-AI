PHASE 7D.2 — SAFE 14:50 / 14:55 ORDERING PATCH

Source basis: RB-ITOS-AI-feature-pcr_HM.zip plus the previously supplied Phase 7D.1 acquisition patch.
This is NOT deployed to your VM until you apply it.

Changes:
* Process available completed 14:50 candle before the 14:55 OPEN cutoff in both
  historical replay and live coordinator; otherwise never wait for missing 14:50
  candle to lock session when exact 14:55 price is already available.
* Guard new trade/option entry when the 5m signal becomes actionable at 14:55.
  Route A/B indicator conditions remain unchanged. 14:50 cross may arm and
  is then cancelled at cutoff. The cutoff guard is a behavioral safety fix.
* While exact cutoff OPEN is delayed, option shadow updates stop at 14:54.
* Tests cover exact ordering, late cutoff, missing bar, no entry, and audit hash chain.

Apply (run from where you unpacked the ZIP):
    python apply_phase7d2.py --repo ~/RB-ITOS-AI
    python apply_phase7d2.py --repo ~/RB-ITOS-AI --apply

Validation:
    cd ~/RB-ITOS-AI && source .venv/bin/activate
    PYTHONPATH=backend python -m pytest -q \
      tests/test_hilega_phase7d2_cutoff_order_v1.py \
      tests/test_hilega_phase7d1_acquisition_v1.py \
      tests/test_hilega_milega_strategy_v1.py \
      tests/test_hilega_milega_live_shadow_v1.py \
      tests/test_hilega_milega_functional_parity_replay_v1.py \
      tests/test_hilega_milega_real_session_parity_v1.py \
      tests/test_hilega_milega_phase7c_pending_exit_v1.py

Run ONLY if broker data for Sep 23 is still obtainable; otherwise preserve d3:
    PYTHONPATH=backend python -m market_lab.hilega_milega_phase7d_historical_capture_v1 \
      --session-date 2026-09-23 --expiry 2026-09-29 \
      --output-root data/historical-evidence/hilega-phase7d-2026-09-23-d4

For parity CLI use: python -m market_lab.hilega_milega_real_session_parity_v1 --help
Then compare NEW d4/step-audit.jsonl with ORIGINAL live append-only audit.
Expect remaining candle differences / build identity uncertainty; this fix does
not retroactively validate Sept 23 full parity or alter past live evidence.

Do not restart live worker automatically. Plan managed deployment separately
when offline VM validation passes. No actual broker orders are enabled.
