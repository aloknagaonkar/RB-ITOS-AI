# Midpoint M2.2

This patch turns the Midpoint historical view from an event-only log into a date-wise full-day validation replay.

The materialized `minutes.jsonl` uses the same V55/V52 loaded underlying and futures source dictionaries that feed the V57 parity-proven replay. The strategy audit remains immutable and separate in `audit.jsonl`; the API overlays projected events onto matching minute timestamps at read time.

No trading rules, lifecycle rules, order behavior, quantity sizing, execution flags, or strategy semantics are changed.
