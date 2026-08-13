# Paper Trading Compact Layout

The Paper Trading workspace prioritizes operational information and keeps diagnostic detail available on demand.

## Default order

1. Trading Overview
2. Current Trades
3. Candidates & Execution Queue
4. Recent Exits
5. Advanced Details & Diagnostics (collapsed)

## Safety

The compact panels read persisted database state only. They do not run candidate discovery, Committee evaluation, trade entry, exit execution, or broker actions.

The complete legacy Paper Trading page remains available inside the collapsed Advanced Details & Diagnostics section, so no diagnostic capability is removed.
