NORMAL_B_PROVED OBSERVATION-ONLY LIVE SHADOW
============================================

Repository branch: feature/pcr-foundation

Install from the repository root:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python normal_b_proved_live_shadow_bundle/install.py

After PASS, restart before market or during an approved maintenance window:

  ./scripts/restart.sh
  ./scripts/status.sh
  curl -fsS http://127.0.0.1:8123/api/health

Safety contract
---------------

This is a parallel observation-only candidate. It cannot close the existing
B/E baseline lifecycle, send an order, create a paper order, set quantity, or
permit re-entry. It only writes candidate audit events and exposes them in the
Midpoint live-shadow UI/status response.

Candidate events
----------------

  NORMAL_B_PROVED_STARTED
  NORMAL_B_PROVED_TIER2
  NORMAL_B_PROVED_TIER3
  NORMAL_B_PROVED_EXIT_CANDIDATE
  NORMAL_B_PROVED_UNAVAILABLE

The candidate activates only after +20 proof and an exact proof+10-minute
NORMAL_B classification. RUNNER_STRENGTHENING trades remain on the baseline.
