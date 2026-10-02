# P3H.5.2.2 fixed-strike OI fallback

Extract/copy the bundle into the repository, then apply the patch:

```bash
git apply p3h522_historical_replay.patch
```

Run the targeted test:

```bash
python -m pytest tests/test_p3h522_fixed_strike_oi_fallback_v1.py -v
```

Then rerun only May 4:

```bash
python -m market_lab.session_strategy_replay_v1 \
  --session-date 2026-05-04 \
  --events exits
```
