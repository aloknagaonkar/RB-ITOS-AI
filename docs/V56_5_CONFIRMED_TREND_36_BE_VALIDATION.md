# V56.5 — Confirmed-trend 36-session B+E cohort screen

This is the requested first test before V57.

Frozen cohort:
- 18 confirmed bullish sessions
- 18 confirmed bearish sessions

This phase is deliberately **event-level** rather than a full strategy
coordinator replay.

For each structural boundary:
- V55 decides one owner: E / B / OTHER_FRESH_A
- E enters at boundary
- B uses the canonical delayed confirmation detector
- B/E entries are labelled TREND_ALIGNED or COUNTER_TREND using the frozen
  confirmed session direction
- post-entry geometry is measured to adverse midpoint close or session end
- +20 proof geometry, MFE, MAE, terminal points and duration are reported

This phase does not apply:
- runner classifier
- DEGRADED
- CAP20
- reentry
- one-active-reference conflict handling

Those belong to the next requested phase:

**V57 — full historical B+E coordinator/lifecycle replay**

No rules or thresholds should be changed based on this cohort output.
