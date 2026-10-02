# Generic OI Session Quantity Replay Template V1

This replaces date-specific replay scripts.

You can now test **any historical date** and **any checkpoint times** already
present in your positioning CSVs.

For every requested checkpoint it calculates:

- current and previous CE OI
- current and previous PE OI
- signed absolute OI change
- absolute OI activity magnitude
- 5-minute percentage change
- total OI
- PCR
- moving ATM
- fixed morning ATM
- arbitrary bands such as ATM only, ±2, ±5

The same physical strikes are compared between T and T-5m.

## Tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_oi_session_quantity_replay_template_v1.py -v
```

## Quick CLI usage

Example: 25 Aug and 7 Sep:

```bash
python -m market_lab.oi_session_quantity_replay_template_v1 \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --session '2026-08-25|13:40,13:45,13:50,13:55,14:00,14:05,14:10' \
  --session '2026-09-07|09:20,09:25,09:30,09:35,09:40' \
  --bands 0,2,5 \
  --fixed-atm-time 09:20 \
  --output data/historical-evidence/oi-session-quantity-replay.json \
  --csv-output data/historical-evidence/oi-session-quantity-replay.csv
```

## Test another day later

Only change this part:

```bash
--session '2026-08-31|09:30,09:35,09:40,09:45'
```

You can repeat `--session` for as many dates as needed.

## JSON request mode

Instead of a long CLI, edit:

`examples/oi-session-replay-request.json`

Then run:

```bash
python -m market_lab.oi_session_quantity_replay_template_v1 \
  --positioning 'TRAIN|data/historical-evidence/positioning-train.csv' \
  --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv' \
  --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv' \
  --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv' \
  --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv' \
  --request-json examples/oi-session-replay-request.json \
  --bands 0,2,5 \
  --fixed-atm-time 09:20 \
  --output data/historical-evidence/oi-session-quantity-replay.json \
  --csv-output data/historical-evidence/oi-session-quantity-replay.csv
```

## Band meanings

- `0` = exact ATM strike only
- `2` = ATM ±2 (5 strikes)
- `5` = ATM ±5 (11 strikes)

You can test another width, e.g. `--bands 0,2,3,5`.

## Important

This is descriptive research only. It does not select a trading threshold,
emit an order, or consume fresh OOS E/F/G/H unless you explicitly pass those
files yourself.
