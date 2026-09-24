# Bearish candidate preservation v5

Corrects a presentation bug in the existing HilegaDecisionTable.

The old lifecycle renderer had one `active` flag. Once a bullish trade was active,
every later DETECTED row was forced to ACTIVE continuation. That hid informational
bearish ARMED/candidate rows even though the directional replay recorded them.

This patch tracks the active direction and preserves an opposite-direction
DETECTED row as a candidate while the active owner remains unchanged.

No UI redesign and no strategy/coordinator changes.
