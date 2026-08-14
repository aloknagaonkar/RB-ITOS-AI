# Historical DRI Point-in-Time Compatibility Hotfix

This hotfix fixes the focused test failure:

`assert "point_in_time_contracts" in source`

The performance patch preserved point-in-time filtering but renamed the helper to
`_contracts_at`. This patch restores the descriptive helper name
`point_in_time_contracts` and updates its call site.

There is no behavioral change. The helper still:

- uses only option-chain snapshots available at or before the DRI event time;
- rejects stale live snapshots;
- slices contract candles to the event timestamp before candidate creation;
- preserves full post-entry candles only for historical exit simulation;
- selects Rank 1 only.

## Apply

```powershell
python .\apply_historical_dri_point_in_time_compat_fix.py
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_dri_committee_wiring.py `
  red_bar_lab/tests/test_historical_dri_replay_performance.py `
  red_bar_lab/tests/test_historical_dri_opportunity_replay.py `
  red_bar_lab/tests/test_historical_dri_replay_ui_wiring.py -q
```

Expected: all tests pass.
