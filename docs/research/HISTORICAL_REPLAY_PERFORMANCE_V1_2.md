# Historical Replay Performance V1.2

The cProfile result identifies the dominant bottleneck precisely.

Measured on 2026-09-18 V1.1 replay:

- total: ~634.7 s
- `process_checkpoint`: ~626.6 s cumulative
- `select_first_snapshot_at_or_after`: ~592.8 s cumulative
- SQLAlchemy result materialization: ~481.3 s
- JSON decoding: ~454.1 s internal time
- Pydantic Snapshot validation: ~99.0 s cumulative
- step audit append/read path: under 2 s total

Therefore the previous suspicion that JSONL audit reconstruction was the primary
problem is incorrect. The primary problem is repeatedly ORM-loading and decoding
the large Observation dataset for every checkpoint.

V1.2 is intentionally historical-replay-only:

1. Query `Observation.snapshot` only once for the selected config/session.
2. Do not load the large `evaluation` JSON column.
3. Build an in-memory index ordered by exact `received_at`.
4. Use binary search for the first snapshot at/after each checkpoint.
5. Keep the exact 30-second eligibility window.
6. Parse a selected snapshot into the Pydantic `Snapshot` only when used, then
   cache it.
7. Leave the production live selector and strategy code unchanged.

Run:

```bash
python -m pytest tests/test_historical_replay_snapshot_index_v1.py -v

time python -m market_lab.historical_replay_day_v1_2 \
  --date 2026-09-18 \
  --overwrite \
  --no-progress \
  > /tmp/replay-v1-2.json

python -m market_lab.historical_replay_parity_v1_2 \
  --baseline data/live-observation/replay-baseline-v1/2026-09-18 \
  --candidate data/live-observation/replay-v1-2/2026-09-18 \
  --output data/live-observation/replay-v1-2/2026-09-18/parity.json
```

Do not switch Replay Operations V1 to V1.2 until the parity report says
`"passed": true`.
