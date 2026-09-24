# Hilega Directional PE ATM±2 Historical Shadow v1

Historical-only PE shadow for accepted BEARISH directional trades.

It tracks all five PE contracts independently:
- ATM-2
- ATM-1
- ATM
- ATM+1
- ATM+2

Semantics:
- entry premium = exact 1m OPEN at the causal signal boundary (5m label + 5m)
- exit premium = exact 1m OPEN at the causal exit boundary (5m label + 5m)
- MFE/MAE measured on the exact minute path
- no nearest-minute fallback
- no nearest-strike fallback
- no single-contract selection
- no quantity
- no rupee P&L
- no paper or live order creation

Real historical option data is read only from existing
`historical-option-ohlc-cache*` files. Missing exact data remains unavailable
or incomplete; it is never synthesized.

Validation against the current source snapshot:
`39 passed`

No API/worker restart is required.
