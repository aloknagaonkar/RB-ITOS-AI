# Offline exit-slope research
Control = installed bullish-gap2-full-wma2-2.0.0-wma40-reversal.
Compare control, bullish falling-WMA normal exit only, bearish rising-WMA normal exit only, both.
Original dual exits remain mandatory. Bearish WMA>40 remains mandatory. Strict negative delta for bullish normal exit, strict positive for bearish normal exit. No minimum absolute slope. No latch; all conditions must pass on same completed5m candle. Delta compares immediately previous completed5m WMA, not entry WMA. Missing/flat slope holds gated normal exit.
Existing confirmed bullish reversal while holding bearish and14:55 cutoff remain unchanged. No new bearish reversal. Entry rules unchanged: no no-touch bypass, no bullish55/60/70 exit thresholds.
Private module namespace; no installed source writes, service operations, orders or live changes.
Tests and replay not executed locally. Run on VM. Defaultdate2026-10-21; --date accepts another saved session. Complete cutoff data and warmup required; control parity validated/cached.
comparison.md contains all policies/trades; exit-validation.md all held-position exit checks; report.json full audit.
