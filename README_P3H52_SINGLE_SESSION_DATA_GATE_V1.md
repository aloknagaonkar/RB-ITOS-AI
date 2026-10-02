# P3H.5.2 single-session workflow

```bash
python -m pytest tests/test_p3h52_single_session_data_gate_v1.py -v
python -m market_lab.session_data_gate_v1 --session-date 2026-05-04
```

Only after PASS:

```bash
python -m market_lab.session_strategy_replay_v1 --session-date 2026-05-04 --events exits
```
