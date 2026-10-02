# P3H.5.2.2 — Exact Fixed-Strike OI Fallback

May 4 exposed a coverage gap caused by the moving ATM ±5 positioning-cache
window. The frozen 09:20 ATM±2 strike 24300 is absent from the positioning
cache at only five timestamps, while the exact same strike/timestamps have
CE and PE open-interest in the historical option-OHLC cache.

This patch keeps strategy rules unchanged.

Fallback rule:

1. positioning cache is authoritative when the exact fixed strike exists;
2. if that fixed strike is absent, use option-OHLC `open_interest` for the
   same timestamp and exact strike;
3. CE and PE must both exist;
4. no nearest-strike substitution;
5. no interpolation;
6. moving ATM±2 recent-5m calculations remain positioning-cache only.
