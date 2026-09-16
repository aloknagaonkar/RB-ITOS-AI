# P2B_UPSTOX_FUTURES_GUARD_V1

Files:

- `backend/market_lab/upstox_live_futures_v1.py`
- `backend/market_lab/paper_market_guard_v1.py`
- `backend/market_lab/paper_futures_health_v1.py`
- `tests/test_p2b_upstox_futures_guard_v1.py`
- `docs/paper/PHASE_P2B_UPSTOX_FUTURES_GUARD_V1.md`

Test:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_p2b_upstox_futures_guard_v1.py -v
```

Then live diagnostic:

```bash
python -m market_lab.upstox_live_futures_v1 diagnose
```

Keep paper disabled.
