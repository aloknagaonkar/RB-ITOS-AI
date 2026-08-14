# Historical DRI Replay UI Wiring

Adds to Research Lab → Historical Decision Replay:

- Replay Sources: RED_BAR, DRI_EARLY, DRI_CONFIRMED
- Historical DRI event table from completed 1-minute candles
- Rank-1 opportunity-level summary for existing Red Bar replay
- Candidate-level detail remains visible
- Existing Red Bar, Committee, Portfolio and Exit engines are not rewritten

Apply:

```powershell
python .\apply_historical_dri_replay_ui_wiring.py
python -m pytest red_bar_lab/tests/test_historical_dri_replay_ui_wiring.py red_bar_lab/tests/test_historical_dri_opportunity_replay.py -q
```

Restart Streamlit after applying.
