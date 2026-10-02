# V62.1 Forward OOS Collector

V62 froze R1/R2 before forward OOS collection.

V62.1 implements the research-only state machine that can automatically collect
new cases. It is deliberately not auto-patched into the current worker because
the worker's exact event/candle plumbing should be inspected first.

The collector needs every completed one-minute underlying candle; audit events
alone are insufficient for R1/R2 because both policies depend on favorable
intrabar excursion and close-based giveback.

The next integration step is therefore:
1. run V62.1 preflight;
2. identify the exact existing audit and completed-candle path;
3. add the smallest possible adapter;
4. run focused tests;
5. only then restart the observation-only worker.

No strategy decisions are changed.
