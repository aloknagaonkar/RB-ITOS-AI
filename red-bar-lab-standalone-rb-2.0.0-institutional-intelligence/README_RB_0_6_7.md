# RB-0.6.7 Trade Outcome & Live P/L Visibility

Data-preserving patch on top of RB-0.6.6.

Trade lifecycle and trade profitability are now separate:

- `status`: OPEN / CLOSED
- `trade_result`: WIN / LOSS / BREAKEVEN / UNKNOWN

Trades tab adds per-signal summary:
- trade models
- winning / losing / breakeven models
- open / closed models
- win rate
- best / worst points
- net model points
- signal lifecycle

Live tab adds:
- entry price
- current price
- live underlying P/L points
- open / closed model count
- signal lifecycle

Live P/L:
- Bullish = current price - entry price
- Bearish = entry price - current price

No existing artifacts or database rows are deleted.
