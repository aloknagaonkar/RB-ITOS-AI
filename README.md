# Hilega decision-table test fixture correction

The production classifier now correctly uses only transitions whose `event_time`
matches the current row checkpoint. The standalone Node test still created some
synthetic transitions without an `event_time`, so those fixtures were ignored
and the first assertion returned `NONE`.

This patch changes only the test helper: any synthetic transition that omits
`event_time` receives the row checkpoint. Explicit future transition times stay
unchanged, so the linked-future-exit/no-lookahead tests remain meaningful.

No application source is modified.
