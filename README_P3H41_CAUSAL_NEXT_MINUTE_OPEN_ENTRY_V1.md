# P3H.4.1 causal entry hotfix

Run:

```bash
python -m pytest tests/test_p3h41_causal_next_minute_open_entry_v1.py -v
```

Then:

```bash
python -m market_lab.historical_option_intrabar_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events exits
```
