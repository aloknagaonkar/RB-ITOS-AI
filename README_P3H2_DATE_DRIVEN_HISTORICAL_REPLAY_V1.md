# P3H.2 date-driven historical replay

Run tests:

```bash
python -m pytest tests/test_p3h2_date_driven_historical_replay_v1.py -v
```

Then:

```bash
python -m market_lab.paper_historical_replay_cli_v1 \
  --session-date 2026-08-25
```

For concise output:

```bash
python -m market_lab.paper_historical_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events signals
```

For range summary only:

```bash
python -m market_lab.paper_historical_replay_cli_v1 \
  --from-date 2026-08-01 \
  --to-date 2026-09-08 \
  --events none
```
