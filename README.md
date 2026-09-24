# Hilega Directional UI Adjustment v1

Frontend-only correction for Phase 6.

This keeps the pre-Phase-6 Hilega page structure and styling, and only adapts
existing sections for directional operation:

- existing safety/header strip retained
- existing summary cards retained, with Trade Owner / Bullish State / Bearish State added
- existing Active Trade card retained; CE for bullish, PE for bearish
- existing candle-by-candle bullish audit retained in its original location
- existing Exited Trades cards retained; combined CE/PE lifecycle data
- large Directional Coordinator Activity table removed from the main page

No backend, strategy, coordinator, API, or live worker changes are included.
No quantity, rupee P&L, execution, paper order, or option selector is introduced.

For bearish trades, the legacy detailed bullish audit button is intentionally
not shown; the PE lifecycle itself is shown in the normal trade card/table.
