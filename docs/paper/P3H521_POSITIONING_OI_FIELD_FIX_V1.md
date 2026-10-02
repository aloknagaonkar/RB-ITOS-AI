# P3H.5.2.1 Positioning OI Field Fix

The data gate incorrectly checked `ce_oi` / `pe_oi`.

The actual historical positioning cache schema uses:

- `ce_open_interest`
- `pe_open_interest`

This patch changes only the validation gate. It does not alter strategy logic,
historical data, P1/P2 rules, or execution assumptions.
