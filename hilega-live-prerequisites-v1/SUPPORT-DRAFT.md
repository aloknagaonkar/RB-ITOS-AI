# Draft broker questions — not sent

Please confirm the timezone and conversion rules for `order_timestamp` and `exchange_timestamp` in the daily trade and per-order trade APIs, and for the order-history timestamps.

For two uniquely matched fills on 2 November 2026, order history shows 13:09:33 and 13:58:06, while both trade endpoints show exchange times 18:39:33 and 19:28:06: exactly 5 hours 30 minutes later. Identity, quantity and price matched across endpoints. Are these fields in different timezones or is a conversion being applied incorrectly? We have retained raw responses and have not shifted the timestamps.

The charges API example permits `ipft: null`. What does null mean for this endpoint, is the amount included in another component or total, and what confirms final report availability? Which documented API or report provides final per-fill fee attribution suitable for reconciliation with a contract note?

Account/order/trade identifiers and original signed capture details can be supplied privately through the broker's support channel. They are intentionally absent from this draft.
