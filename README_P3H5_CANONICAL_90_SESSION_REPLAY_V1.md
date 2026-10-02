# P3H.5 canonical 90-session replay

First verify universe only:

```bash
python -m market_lab.historical_multi_session_replay_cli_v1 \
  --universe-only
```

It must report:

```text
count: 90
```

Then run tests:

```bash
python -m pytest \
  tests/test_p3h5_canonical_90_session_replay_v1.py -v
```

Then run the full replay:

```bash
python -u -m market_lab.historical_multi_session_replay_cli_v1
```

Outputs are also written to:

```text
data/historical-evidence/p3h5-canonical-90-session-replay-v1.json
data/historical-evidence/p3h5-canonical-90-session-replay-v1.csv
```

Do not use `--allow-non90` for strategy conclusions. It exists only for
diagnosing missing cache coverage.
