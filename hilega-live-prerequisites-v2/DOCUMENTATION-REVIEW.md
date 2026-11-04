# Upstox documentation review — 3 November 2026

These are field-contract observations, not broker support confirmation or execution clearance.

- Trades: https://upstox.com/developer/api-documentation/get-trade-history/ and order-specific trades: https://upstox.com/developer/api-documentation/get-trades-by-order/ describe `exchange_timestamp` as the trade occurrence string and `order_timestamp` as the order-placement string. The reviewed trade page does not specify a timezone for them. Our captured 19,800-second discrepancy remains unresolved; changing VM timezone cannot establish broker field semantics. No automatic shift is implemented.
- Charges: https://upstox.com/developer/api-documentation/get-trade-charges/ explicitly shows `charges.ipft: null` in its example. This does not establish that null equals zero, nor that fees are final or allocated per fill. Null-component arithmetic is reported as not assessable, not a demonstrated mismatch.
- Historical trades: https://upstox.com/developer/api-documentation/get-historical-trades/ documents the GET date-range endpoint, FO selection, trade ID, exchange, side, quantity, price and trade date. Examples use `meta_data.page` while the field table uses `metadata.page`. The parser accepts either spelling and rejects conflicting aliases. Historical date-only rows cannot establish the execution timestamp timezone or strategy ownership.

No numeric charge rates or estimated fees are substituted for broker evidence. No response has been promised by Upstox and no support message has been sent.
