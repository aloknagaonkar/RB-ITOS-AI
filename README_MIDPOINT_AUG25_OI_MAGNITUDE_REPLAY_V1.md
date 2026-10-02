# MIDPOINT_AUG25_OI_MAGNITUDE_REPLAY_V1

Adds the OI magnitude layer to the earlier 25-Aug replay.

Existing:
- ATM OI state
- price structure
- VWAP state/distance

New:
- overall CE/PE OI
- absolute OI change
- OI change %
- option price change %
- derived OI state
- OI change acceleration
- ATM and ATM ±2 aggregate views

Morning checkpoints:
09:20, 09:25, 09:30, 09:35, 09:40

Afternoon checkpoints:
13:35, 13:40, 13:45, 13:50, 13:55, 14:00, 14:05, 14:10

No trading threshold is chosen.

Run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_midpoint_aug25_oi_magnitude_replay_v1.py -v

python -m market_lab.midpoint_aug25_oi_magnitude_replay_v1   --positioning data/historical-evidence/positioning-train.csv   --output data/historical-evidence/midpoint-aug25-oi-magnitude-replay-v1.json
```

If `positioning-train.csv` does not contain raw CE/PE OI and option-price columns,
the script deliberately stops and prints the available columns. Do not invent OI
percentages. We will then point the script at the existing raw positioning source
that actually contains those fields.

Inspect:

```bash
jq '{
  morning: .morning_failed_setup,
  afternoon: .afternoon_successful_transition,
  integrity
}' data/historical-evidence/midpoint-aug25-oi-magnitude-replay-v1.json
```
