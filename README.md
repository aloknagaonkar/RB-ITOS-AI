# Phase 6.2 — Common directional candle audit

Historical replay now reads the recorded directional candle-by-candle evidence, so
both bullish and bearish state/action/event rows are visible.

Live shadow keeps current-day candle/indicator rows from the existing Hilega audit
and overlays directional ownership/state only for bars present in the directional
audit. Earlier rows remain visible as candle-only evidence instead of fabricating
directional state.

No strategy, coordinator, option lifecycle, selector, quantity, rupee P&L or
execution behavior is changed.
