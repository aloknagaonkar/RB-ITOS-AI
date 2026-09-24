# Hilega Directional CE Historical Shadow + Unified Replay UI v1

Purpose: complete historical UI parity for both directional sides without changing
the strategy/coordinator/live worker.

BULLISH -> existing frozen CE candidate builder + existing frozen CE lifecycle
BEARISH -> existing PE historical shadow (unchanged)

New CE evidence root:
`data/historical-evidence/hilega-directional-ce-shadow-v1`

Historical UI then reads:
- CE shadow for accepted bullish trades
- PE shadow for accepted bearish trades

Safety: observation-only, no execution, no paper orders, no quantity, no rupee P&L,
no selector, no nearest-minute/strike fallback.
