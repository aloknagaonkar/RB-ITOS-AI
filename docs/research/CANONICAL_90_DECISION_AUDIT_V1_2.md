# Canonical 90 Decision Audit V1.2 — Futures 5m Causal Fix

The real futures source is 1-minute data, with columns including timestamp,
close and open_interest. V1 incorrectly treated those rows as completed 5-minute
bars, so it never derived futures OI states.

V1.2:
- groups exact 1-minute rows into exact completed 5-minute bars;
- uses the last minute's close and OI for each 5-minute bar;
- compares each completed bar with the immediately preceding exact 5-minute bar;
- indexes the result by bar-end / decision-available timestamp;
- preserves the existing futures-state rules:
  price up + OI up = LONG_BUILDUP
  price down + OI up = SHORT_BUILDUP
  price up + OI down = SHORT_COVERING
  price down + OI down = LONG_UNWINDING

No nearest-time fallback. No strategy-rule change. No option replay added.
