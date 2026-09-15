# MIDPOINT_ARM_C_DIRECTION_SPLIT_V1 FIX1

Fixes source-schema selection.

The controlled-comparison artifact stores:
- `arm_c`: summary/by-block data
- `arm_c_trades`: the actual top-level 49-trade array

V1 incorrectly attempted to read `arm_c.trades`, producing an empty population.

FIX1 reads the canonical top-level `arm_c_trades` and fails hard if its length does not match `comparison.arm_c_trade_count`.
