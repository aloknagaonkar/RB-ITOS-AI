# HILEGA MTF Alignment Research V1

Research-only comparison of the existing 5-minute directional entries against
completed 10-minute and 15-minute higher-timeframe alignment.

Default 14 sessions intentionally end on 2026-09-23, excluding current-day
2026-09-24 so the first experiment uses completed historical sessions only.

Versions:
- V1: current 5m entry baseline.
- V2: 5m trigger + 10m full alignment.
- V3: 5m trigger + 15m full alignment.
- V4: 5m trigger + 10m + 15m full alignment.
- V5: 5m trigger + 10m/15m non-opposition.

All versions retain the baseline 5m exit time/price. HTF bars are causal:
only bars completed by the 5m decision boundary are visible.

No live strategy or worker changes.
