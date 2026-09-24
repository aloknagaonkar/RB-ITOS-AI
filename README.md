# Directional event-kind precedence v7

The directional replay already contains bearish candidate and bearish entry/exit
evidence. The remaining UI issue was classification order.

`eventKind()` previously tested ACTIVE before DETECTED. When BULLISH owned the
trade and BEARISH was simultaneously ARMED, `state_after=BULLISH_ACTIVE` caused
the row to become BULLISH_CONTINUATION before the candidate evidence was checked.

This patch checks explicit directional ARMED/candidate evidence before ACTIVE.
The existing UI/CSS is unchanged.
