# Historical DRI + Opportunity-Level Replay Foundation

This additive increment adds Rank-1 opportunity accounting and point-in-time completed-1m DRI event detection. It does not yet replace the existing replay UI summary or execute DRI through Committee.

Apply:

```powershell
python .\apply_historical_dri_opportunity_replay.py
python -m pytest red_bar_lab/tests/test_historical_dri_opportunity_replay.py -q
```
