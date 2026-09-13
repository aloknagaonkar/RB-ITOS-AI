# Midpoint Failure Feature Diagnostics V2.1

This module explains the V2 strength/failure results instead of adding another
opaque score.

It compares CONTINUATION vs REVERSAL at T+1 and T+3 for RED/bearish and
GREEN/bullish separately.

For every checkpoint it reports:
- median/mean/min/max for each price feature;
- continuation vs reversal median gap;
- OI support-level distribution;
- exact CE|PE state-pair distribution;
- OI transition labels;
- T+1 -> T+3 CE/PE state transitions;
- the same analysis separately for TRAIN and OOS-A/B/C/D.

Price features:
1. momentum_5m
2. acceptance_pct
3. consecutive_closes
4. extreme_count
5. progress_points
6. velocity
7. rebound_points
8. midpoint_cross_count

No new thresholds are selected here. No P&L is used. No entry rule is changed.
E/F/G/H are excluded and OOS-H remains pristine.
