# P3H.4 intrabar option OHLC replay

Tests:

```bash
python -m pytest tests/test_p3h4_intrabar_option_ohlc_replay_v1.py -v
```

Replay:

```bash
python -m market_lab.historical_option_intrabar_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events exits
```

Full stop-state audit:

```bash
python -m market_lab.historical_option_intrabar_replay_cli_v1 \
  --session-date 2026-08-25 \
  --events all
```
