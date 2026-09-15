# MIDPOINT_AUG25_OI_MAGNITUDE_REPLAY_V1_FIX1

This fixes the first OI-magnitude replay.

## What changed

The old version compared a checkpoint against the immediately previous raw row.
That could accidentally produce a 1-minute or sub-5-minute delta.

FIX1 now compares exact checkpoints:

- 09:25 vs 09:20
- 09:30 vs 09:25
- 09:35 vs 09:30
- 09:40 vs 09:35

and:

- 13:40 vs 13:35
- 13:45 vs 13:40
- 13:50 vs 13:45
- 13:55 vs 13:50
- 14:00 vs 13:55
- 14:05 vs 14:00
- 14:10 vs 14:05

It also:
- compares the SAME strike across t-5 and t
- explicitly reports ATM changes
- computes ATM ±2 aggregates using identical strike sets
- prints overall OI, absolute OI change and true 5-minute OI change %
- does not choose any threshold

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_midpoint_aug25_oi_magnitude_replay_v1_fix1.py -v
```

## Run

```bash
python -m market_lab.midpoint_aug25_oi_magnitude_replay_v1_fix1 \
  --positioning data/historical-evidence/positioning-train.csv \
  --output data/historical-evidence/midpoint-aug25-oi-magnitude-replay-v1-fix1.json
```

## Inspect

```bash
jq '{
  morning: .morning_failed_setup,
  afternoon: .afternoon_successful_transition,
  integrity
}' \
data/historical-evidence/midpoint-aug25-oi-magnitude-replay-v1-fix1.json
```

Research only. Do not derive a trading threshold from this one session.
