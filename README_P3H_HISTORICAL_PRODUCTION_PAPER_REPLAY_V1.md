# P3H historical production-paper replay V1

Files:

- `backend/market_lab/paper_historical_replay_v1.py`
- `backend/market_lab/paper_historical_replay_cli_v1.py`
- `tests/test_p3h_historical_paper_replay_v1.py`
- `docs/paper/P3H_HISTORICAL_PRODUCTION_PAPER_REPLAY_V1.md`

Run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_p3h_historical_paper_replay_v1.py -v
```

The replay core is ready. The repository-specific historical futures/option adapter is intentionally not guessed.
After tests pass, inspect the actual historical file format and wire the adapter.
