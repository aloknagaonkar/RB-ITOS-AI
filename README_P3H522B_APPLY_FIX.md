# P3H.5.2.2b apply-fix

The previous `.patch` file was malformed. This bundle replaces that step with
a deterministic Python integration script that only applies if the exact
expected source blocks are present.

After copying this bundle into the repo:

```bash
python tools/apply_p3h522b_fixed_strike_oi_fallback.py
```

Then inspect:

```bash
git diff -- backend/market_lab/historical_paper_replay_date_v1.py
```

Run:

```bash
python -m pytest tests/test_p3h522_fixed_strike_oi_fallback_v1.py -v
```

Finally rerun May 4:

```bash
python -m market_lab.session_strategy_replay_v1 \
  --session-date 2026-05-04 \
  --events exits
```
