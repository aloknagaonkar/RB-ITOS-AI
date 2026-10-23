# Body-cross breakout waiting — research only

Additional entry route alongside installed v2 WMA40/reversal strategy. No live
source changes, services, orders or deployment. Requires actual session candles.

Only new setups emitted by the recalculated 5m strategy can arm the extra route.
Signal: directional body crossing price EMA10, >50% of body beyond EMA10,
body >=60% of range, close in directional outer25%, price EMA10 directional slope.
Strength, gap, expansion and bullish WMA magnitude are NOT required by this extra
route. They remain unchanged for existing entries. No new RSI filter is added.
Wick-only touches and zero-range candles cannot qualify.

Each later completed1m close: bullish enter above original5m high, cancel below
original midpoint; bearish enter below low, cancel above midpoint. Equality waits.
No fixed minute expiry; qualified opposite watch override or new eligible opposite
body signal replaces/cancels waiting. Earliest same-side signal reference retained.
At coincident5m boundaries existing strategy evaluates first. Existing confirmed
entry takes precedence. Entries are hypothetical completed1m close marks.

After entry existing5m normal exits and bearish confirmed-bullish reversal remain;
bearish monitor is initialized on the additional bearish entry.14:55cutoff uses
the saved14:55minute open. One active position only. Extra route does not forcibly
reverse an active position. Setup generation is recalculated, not taken from the
old trade list. Full JSON records every extra route waiting/cancellation decision.

VM validation required: tests here check pure signal/wait rules only; they do not
prove integration parity for the new route. Baseline recorded parity is checked
before producing a comparison. No tests or project replays run locally.

## Wider sessions

batch.py accepts --month (default2026-10), repeated --date, --input-zip,
--session-input and --output. Only supplied saved sessions are selected.
Each completed day is atomically saved with input/source fingerprint and payload
checksum. Matching completed sessions are reused on rerun. Failed sessions are
excluded from totals and cause a nonzero final exit. Independent installed5m
baseline is recalculated per day; recorded audit parity is also required where
provided. Additional-route warmup is incrementally prepared and deep-copied per
session. No indicator periods or trading rules change from the Oct22 test.

summary.md includes daily net impact; daily-trades.md includes every executed
trade; signal-comparison.md groups by exact setup identity. Different setup
identities are not automatically paired as the same trade. JSON holds full extra
route waiting evidence. Costs are excluded. Run one process per output directory.
