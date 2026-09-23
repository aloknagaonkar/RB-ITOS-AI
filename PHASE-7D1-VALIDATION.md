# Phase 7D.1 — local validation and safe VM handoff

Validated against the supplied `RB-ITOS-AI-feature-pcr_HM.zip` snapshot with the already-supplied `hilega-phase7d1-patch.zip` applied. This is **not** evidence of VM deployment or live/broker parity.

## Test evidence

- Five relevant Phase 7D/7C/live test modules: **37 passed**.
- Full offline repository suite: **1,135 passed, 13 failed**.
- The same 13 failing tests were reproduced against the **original, unpatched attached repository** (17 passed, 13 failed when running the seven affected test modules). The failures are therefore present in the supplied baseline; they are not introduced by the Phase 7D.1 patch as observed in this environment.
- The failures concern older historical-OI frontend/fixture assertions, multi-session evidence expectations, and P3H4 intrabar stops. Do not treat the full suite as passing or modify unrelated strategy components just to clear these tests.

## Safe VM procedure

1. Transfer the previously supplied `hilega-phase7d1-patch.zip` and this `apply_phase7d1_safely.py` to `~/` on the Google Cloud VM. The script checks the **exact hashes from the attached repository snapshot**; it will refuse to overwrite different VM files.
2. `cd ~/RB-ITOS-AI && git status --short && git branch --show-current` — verify the current branch and check for local modifications.
3. Dry-run: `python ~/apply_phase7d1_safely.py --repo ~/RB-ITOS-AI --patch ~/hilega-phase7d1-patch.zip`.
4. If no conflicts, and after reviewing intended changes: `python ~/apply_phase7d1_safely.py --repo ~/RB-ITOS-AI --patch ~/hilega-phase7d1-patch.zip --apply`.
5. `git diff --check && git diff --stat && git status --short`.
6. `source .venv/bin/activate && PYTHONPATH=backend python -m pytest -q tests/test_hilega_phase7d1_acquisition_v1.py tests/test_hilega_milega_functional_parity_replay_v1.py tests/test_hilega_milega_real_session_parity_v1.py tests/test_hilega_milega_phase7c_pending_exit_v1.py tests/test_hilega_milega_live_shadow_v1.py`.
7. Run the capture offline, using a NEW output directory:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
PYTHONPATH=backend python -m market_lab.hilega_milega_phase7d_historical_capture_v1 \
  --session-date 2026-09-23 --expiry 2026-09-29 \
  --output-root data/historical-evidence/hilega-phase7d-2026-09-23-d1
```

**Important:** The intraday endpoint is valid for current-session capture only. If you run the capture on a later IST date, the corrected code selects the historical endpoint for September 23. Do not assume the broker has made the September 23 history available. A zero-candle response should be reported as unavailable, not captured. Record actual manifest counts, exact five-strike option coverage and parity verdict before claiming success.

The script will **not** restart/duplicate the live worker, place orders, enable paper trading, or overwrite original market evidence. Restart/deployment of live services remains a separately reviewed step after VM test verification.
