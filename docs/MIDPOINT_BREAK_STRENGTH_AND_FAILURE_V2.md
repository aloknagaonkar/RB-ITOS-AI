# Midpoint Break Strength and Failure V2

This research module studies whether the primary RED/ GREEN boundary break is
being accepted or is starting to fail at T0, T+1 and T+3.

It includes all four option positioning states:

- LONG_BUILDUP
- SHORT_BUILDUP
- LONG_UNWINDING
- SHORT_COVERING

Strong bearish = CE SHORT_BUILDUP + PE LONG_BUILDUP.
Explicit bearish failure warning = CE SHORT_COVERING + PE LONG_UNWINDING.

Strong bullish = CE LONG_BUILDUP + PE SHORT_BUILDUP.
Explicit bullish failure warning = CE LONG_UNWINDING + PE SHORT_COVERING.

Price evidence includes directional momentum, acceptance, consecutive closes,
new extremes, progress, velocity, adverse rebound and midpoint-cross count.

Numeric thresholds are derived from TRAIN only. A/B/C/D validate unchanged.
E/F/G/H remain excluded and OOS-H remains pristine.

Research states:
- STRONG_CONTINUATION_EVIDENCE
- MIXED_WAIT
- FAILURE_WARNING

This module does not alter the frozen V1 entry rule, use P&L for selection, or
emit orders.
