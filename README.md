Fixes the direction-priority bug for informational ARMED rows.

Previously, if BULLISH owned the trade, a simultaneous BEARISH_PATH1_ARMED row
was labeled BULLISH because owner_after was checked before bearish candidate evidence.

This patch makes candidate evidence/armed flags take precedence over trade owner
for DETECTED rows, while leaving ACTIVE ownership semantics unchanged.
