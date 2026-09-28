# V62.2 exact coordinator adapter

The current worker invokes `midpoint_coord.process(now)`, while the midpoint
coordinator itself fetches and de-duplicates completed 1-minute underlying data
and emits the audit events. Therefore the collector is attached to the
coordinator, not to the outer worker.

Research event order for each completed minute:
1. non-terminal audit events
2. completed underlying candle
3. structural-terminal audit event

This lets R1/R2 evaluate the terminal candle before the forward case is finalized.

The feature is disabled unless `MIDPOINT_V62_OOS_COLLECTOR_ENABLED=1`.
