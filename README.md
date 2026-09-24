# Hilega directional historical UI v1

Adds a read-only directional trade dashboard to the existing Hilega historical
replay page.

It does not create a second replay screen and does not redesign the existing UI.

Evidence sources:
- accepted ownership/trades: `hilega-directional-replay-v1`
- bullish CE lifecycle: existing canonical `hilega-milega-replay-v1` audit
- bearish PE lifecycle: `hilega-directional-pe-shadow-v1`

The frontend renders the same trade-card semantics as live:
- BULLISH -> CE ATM±2
- BEARISH -> PE ATM±2
- same entry/exit premium, realized points/%, MFE/MAE presentation

Safety:
- read only
- observation only
- no quantity
- no rupee P&L
- no order execution
- no selector
- no broker calls
