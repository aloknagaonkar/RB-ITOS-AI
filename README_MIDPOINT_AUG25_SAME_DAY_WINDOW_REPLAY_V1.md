# MIDPOINT_AUG25_SAME_DAY_WINDOW_REPLAY_V1

Compares 2026-08-25:
- 09:15 -> 09:55
- 13:40 -> 14:30

Run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_midpoint_aug25_same_day_window_replay_v1.py -v

python -m market_lab.midpoint_aug25_same_day_window_replay_v1 \
  --underlying data/historical-evidence/underlying-ohlc-train.csv \
  --futures-vwap data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv \
  --positioning data/historical-evidence/positioning-train.csv \
  --output data/historical-evidence/midpoint-aug25-same-day-window-replay-v1.json
```

Inspect:

```bash
jq '{
  session_date,
  early: .windows.early_0915_0955,
  late: .windows.late_1340_1430,
  integrity
}' data/historical-evidence/midpoint-aug25-same-day-window-replay-v1.json
```
