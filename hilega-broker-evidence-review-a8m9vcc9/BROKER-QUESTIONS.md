# Upstox support questions — draft, not sent

Please clarify timestamp and final charge semantics for account activity on 2 November 2026. We retained raw API responses without shifting timestamps.

For two uniquely matched fills, order history shows 13:09:33 and 13:58:06, while daily and per-order trade exchange_timestamp shows 18:39:33 and 19:28:06, exactly 5h30m later. Which timezone/offset applies to each timestamp field? Is a conversion defect involved? Please identify the documented contract and any correction or version boundary. Identifiers can be provided privately in the broker support channel.

The charges API returns charges.ipft=null. What does null represent, where (if anywhere) is that component included, and what establishes report finality? Which final contract note/report and documented method support exact per-fill component attribution, including rounding? We have not treated null as zero or aggregate net cashflow as certified strategy P&L.

Please also clarify historical trade pagination reporting total_pages=0 while total_records=2 and page_size=100. We retained the raw metadata and verified the collected row count, without assuming the zero-page semantics.

## Values recomputed from the verified saved capture

- Order field: 2026-11-02T13:09:33; trade exchange field: 2026-11-02T18:39:33
- Order field: 2026-11-02T13:58:06; trade exchange field: 2026-11-02T19:28:06

