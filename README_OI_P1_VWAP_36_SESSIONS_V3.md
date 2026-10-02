# OI P1 + VWAP 36 Sessions V3

This version uses the exact confirmed `OI_PATTERN_CONTROL_TIMING_V1` schema:

- `ce_delta_5m`
- `pe_delta_5m`
- `activity_5m`
- `imbalance_5m`
- `pcr_previous_5m`
- `pcr_current_5m`
- `pcr_change_5m`
- `session_activity`
- `session_imbalance`
- `pcr_session_change`
- `persists_1cp` ... `persists_4cp`
- `directional_move_5m_points` ... `directional_move_20m_points`

No guessed field names and no separate outcome join are needed.

Population is exactly 36 frozen trend sessions:
18 bullish + 18 bearish.

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_oi_p1_vwap_36_sessions_v3.py -v

python -m market_lab.oi_p1_vwap_36_sessions_v3 \
  --pattern-events data/historical-evidence/oi-pattern-control-timing-v1.json \
  --vwap-profile data/historical-evidence/vwap-trend-day-profile-v1.json \
  --output data/historical-evidence/oi-p1-vwap-36-sessions-v3.json \
  --csv-output data/historical-evidence/oi-p1-vwap-36-sessions-v3.csv

python -m market_lab.oi_p1_vwap_36_sessions_report_v3 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v3.json
```

Aug 25:

```bash
python -m market_lab.oi_p1_vwap_36_sessions_report_v3 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v3.json \
  --date 2026-08-25
```

Sep 8:

```bash
python -m market_lab.oi_p1_vwap_36_sessions_report_v3 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v3.json \
  --date 2026-09-08
```
