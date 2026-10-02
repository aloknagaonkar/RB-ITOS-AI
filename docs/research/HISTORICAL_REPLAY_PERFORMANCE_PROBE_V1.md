# Historical Replay Performance Probe V1

This probe is the safe first step before changing replay internals.

The completed 2026-09-18 baseline is valuable because it provides a concrete
parity target:

- 74/74 checkpoints
- 0 missing checkpoints
- 8 observations
- 3 CLOSED
- 5 REJECTED
- 418 audit rows
- valid audit hash chain

The baseline command copies the completed replay artifacts into an immutable
comparison directory and records SHA-256 hashes.

The profile command runs the same V1.1 replay into a separate output root under
cProfile. It does not overwrite the production replay baseline.

Commands:

```bash
python -m pytest tests/test_historical_replay_performance_probe_v1.py -v

python -m market_lab.historical_replay_performance_probe_v1 baseline \
  --date 2026-09-18

python -m market_lab.historical_replay_performance_probe_v1 profile \
  --date 2026-09-18 \
  --limit 80
```

After profiling:

```bash
sed -n '1,180p' \
  data/live-observation/replay-profile-v1/profiles/2026-09-18-top.txt
```

Only after the hotspot is measured should V1.2 optimize the relevant state,
audit, cache, or snapshot path. Strategy semantics are out of scope.
