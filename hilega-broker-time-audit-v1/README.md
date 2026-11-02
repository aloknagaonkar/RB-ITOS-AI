# Broker timestamp cross-endpoint audit

Run `.venv/bin/python hilega-broker-time-audit-v1/manage.py --repo "$PWD"`. Reuses the 74-case plus seed-preflight PASS receipt, verifies installed closed recovery before/after, runs eight new pure comparison tests, then captures account-bound GET evidence from the exact running source read context.

Reads profile, day orders/trades, positions and up to five matched orders through two additional fixed documented GET endpoints: /v2/order/history and /v2/order/trades with URL-encoded order_id. Uses the existing no-redirect Client transport and identical truthful application User-Agent. No retries, token rotation, alternate identities or mutations. A maximum 120-second collection is diagnostic only; it is not entry-freshness or atomic-account clearance.

Matches fills by order/trade IDs and identity, quantity and price, but prints no IDs, symbols, prices, balances or tokens. Raw broker rows and locally signed account-bound evidence remain in a private audit folder. Compares naive timestamps only as naive wall clocks; explicit offsets are retained; mixed offset/naive comparisons are not inferred. No time is automatically corrected and matching endpoints do not establish a timezone contract. HTTP Date observations assist clock diagnosis without asserting NTP correctness.

Creates PUBLIC-COMPARISON.json, PRIVATE-ACCOUNT-BOUND-EVIDENCE.json and SUPPORT-REVIEW.json. No support message is sent. Current-day APIs may no longer return prior-day records; empty results do not resolve previously observed anomalies. Live controller, service state, database rows and installed normalizer remain unchanged.

Official endpoint references: https://upstox.com/developer/api-documentation/get-trades-by-order/ and https://upstox.com/developer/api-documentation/get-order-history/ .

Behavioral tests run on VM only; local checks are syntax/archive only.
