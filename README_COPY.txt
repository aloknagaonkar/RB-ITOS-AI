FIXED EVENT OI BASKET COMPARISON V2
======================================

Purpose
-------
Research-only comparison of fixed physical ATM +/-2 and ATM +/-5 option OI
around a known event boundary. It does not modify live strategy logic.

Copy into the root of ~/RB-ITOS-AI preserving folders:

scripts/analyze_fixed_event_oi_baskets_v2.py
tests/test_analyze_fixed_event_oi_baskets_v2.py

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_analyze_fixed_event_oi_baskets_v2.py -v

Run for 2026-09-21
------------------
python scripts/analyze_fixed_event_oi_baskets_v2.py \
  --date 2026-09-21 \
  --expiry 2026-09-22 \
  --from-time 10:10 \
  --to-time 11:05 \
  --baseline-time 10:35 \
  --event-time 10:40 \
  --wings 2 5

Important semantics
-------------------
- 10:35 moving ATM from NORMALIZED_FEATURES is frozen for the event study.
- ATM +/-2 and ATM +/-5 use the same exact physical strikes for every checkpoint.
- Checkpoint T uses exact completed 1-minute OI at T-1 minute.
- No nearest strike.
- No nearest timestamp.
- No interpolation.
- No partial basket.
- Any missing required contract/minute/OI fails closed.

Expected fixed strikes when 10:35 ATM = 23350
----------------------------------------------
ATM +/-2: 23250, 23300, 23350, 23400, 23450
ATM +/-5: 23100, 23150, 23200, 23250, 23300, 23350, 23400, 23450, 23500, 23550, 23600

Outputs
-------
data/live-observation/analysis/2026-09-21-fixed-event-oi-pm2-summary-v2.csv
data/live-observation/analysis/2026-09-21-fixed-event-oi-pm2-per-strike-v2.csv
data/live-observation/analysis/2026-09-21-fixed-event-oi-pm5-summary-v2.csv
data/live-observation/analysis/2026-09-21-fixed-event-oi-pm5-per-strike-v2.csv

The script uses the existing UPSTOX_ACCESS_TOKEN from .env and the existing
UpstoxIntradayAnchorSourceV1 provider path.
