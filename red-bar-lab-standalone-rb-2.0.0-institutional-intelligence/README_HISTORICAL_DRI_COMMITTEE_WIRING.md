# Historical DRI Rank-1 Committee Wiring

Apply from the project root:

```powershell
python .\apply_historical_dri_committee_wiring.py
```

Validate:

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_dri_committee_wiring.py `
  red_bar_lab/tests/test_historical_dri_opportunity_replay.py `
  red_bar_lab/tests/test_historical_dri_replay_ui_wiring.py -q
```

Restart Streamlit, then open:

`Research Lab → Historical Decision Replay → DRI_EARLY`

The DRI section will show **DRI Rank-1 Committee & Exit Replay**.

Safety:
- Red Bar remains unchanged.
- One Rank-1 contract per DRI bundle.
- Entry uses point-in-time option snapshots.
- Future option candles are used only after the decision by the existing Exit Engine.
- Shadow remains informational-only.
- Existing Committee, Portfolio and Exit thresholds are reused unchanged.
