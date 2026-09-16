# P3H.3 Historical Option Paper Replay V1

Run tests:

```bash
python -m pytest tests/test_p3h3_historical_option_paper_replay_v1.py -v
```

Replay Aug 25:

```bash
python -m market_lab.historical_option_paper_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events trades
```

Summary only:

```bash
python -m market_lab.historical_option_paper_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events none
```
