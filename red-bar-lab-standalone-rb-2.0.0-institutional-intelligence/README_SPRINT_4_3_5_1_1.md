# Sprint 4.3.5.1.1 — Historical Bundle Backfill and Filtering

Install over branch:

`feature/sprint-4.3.5.1-historical-attribution-audit`

## Adds

- deterministic historical v4.3 backfill per completed 5-minute bar;
- historical regime snapshots;
- historical transition records;
- deterministic historical transition IDs;
- historical fresh setup signals;
- historical setup bundles;
- duplicate-safe reruns;
- source filtering diagnostics.

## Filtering diagnostics

Each source now shows:

- raw rows;
- rows inside selected date range;
- rows inside selected session;
- rows matching the instrument;
- rows matching the requested direction;
- final matching rows.

## Safety

The backfill may write only these research artifacts:

- `stateful_regime_v43`
- `transition_sequence_v43`
- `fresh_setup_signals_v43`
- `fresh_setup_bundles_v43`

It never writes:

- candidate records;
- opportunity evaluations;
- Committee decisions;
- execution queue;
- paper orders;
- live orders.

## UI

`Shadow Directional -> Historical Attribution Replay`

Use:

1. Select date range/session.
2. Click **Backfill missing v4.3 bundles**.
3. Review backfill summary.
4. Click **Run read-only historical audit**.
5. Review raw-to-filtered source counts and matches.

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_attribution_audit.py `
  red_bar_lab/tests/test_historical_bundle_backfill_filtering.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```
