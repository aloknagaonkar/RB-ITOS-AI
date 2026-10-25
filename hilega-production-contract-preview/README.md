# Pinned-account read-only contract/quote preview

NO install/apply, UI changes, strategy changes, orders, reservation or entry
permissions. This standalone collector reads .env locally, verifies the existing
private Upstox account pin before and after collection, and saves only selected
contract/quote fields and cash preview. Raw profiles, tokens, account IDs and
complete API bodies are never printed or persisted. Output directories/files
are private; keep reports out of public Git because cash values are sensitive.

Requires installed account adapter and funds-schema milestone. Default private
pin is ~/hilega-private/upstox-account-pin.json. No re-enrollment is needed.
Conflicting shell/.env values fail instead of silently selecting another token.
Uses HILEGA_PRODUCTION_BROKER_READ_TOKEN, otherwise UPSTOX_ACCESS_TOKEN.

VM only: run pytest test_rules.py, then run.py --output NEW_DIRECTORY.
Defaults: offsets 0, one lot, nearest nonexpired broker-returned expiry; both
CE and PE displayed as separate alternative baskets, never bought together.
Examples:
--offsets=0 --lots 1
--offsets=-1,0,1 --lots 1
--offsets=-2,-1,0,1,2 --lots 2
Optional --expiry YYYY-MM-DD selects exact returned expiry; no expiry-day calendar
is hardcoded. Contract availability/selection does not establish trading readiness.

ATM nearest returned strike, tie chooses higher. Step inferred from minimum
returned adjacent strike difference; offset means numerically higher/lower strike,
NOT relative moneyness (CE and PE moneyness differ). Missing/duplicate contracts,
underlying mismatch, bad lot/minimum/freeze quantities fail rather than substitute.
An ATM change during collection requires rerun. Lot size comes from API metadata.
No order splitting when requested quantity exceeds freeze quantity.

Read-only fixed GET routes only:
/v2/option/contract?instrument_key=NSE_INDEX|Nifty 50
/v2/market-quote/quotes (underlying + selected contract keys)
/v2/market/status/NSE
Existing fixed Client: profile and /v3/user/get-funds-and-margin.
No redirects, arbitrary URL, order endpoint or mutation transport is provided.

Draft research checks (NOT yet approved production risk settings):
- Current market status NORMAL_OPEN at start/end; captured within 30 seconds.
- Underlying and option quote timestamp age <=10 seconds, no future timestamps.
- Last option trade <=60 seconds; this differs from quote response freshness.
- Positive two-sided book; no crossed book; spread <=2% of midpoint.
- Best ask AND bid quantity covers requested quantity; positive traded volume.
- Budget cap: 50% cash_available_to_trade.total; excludes pledge.
- Cost: ask * broker lot size * configured lots + provisional INR100 per leg.
  --buffer changes this research estimate; it is NOT broker-calculated charges.
  --max-spread changes provisional spread percent only.
- Directional basket total compared with cap; never automatically increases lots
  to consume the cap. Cash is not reserved; no outstanding-order/exposure subtraction
  or concurrency protection. These are separate pending production work.

Exit code 0 = READ_ONLY_CHECKS_PASS (still no entry permission).
Exit code 2 = NOT_CLEARED or BLOCKED. Closed markets/stale quotes are expected
outside trading hours and must not be relabelled PASS. Schema issues need review.
Today Sunday 25 October may resolve metadata but cannot demonstrate live quotes.
Use a fresh output directory for the next market-hours sample.

REST quote access does NOT verify Plus WebSocket entitlements, feed continuity,
real orders/fills, broker external exits, realised P&L or production readiness.
Cash mapping still needs private comparison with broker account UI. Preview is
an observation at collection time, not a reusable trade authorization.

Official references checked 25 October 2026:
https://upstox.com/developer/api-documentation/get-option-contracts/
https://upstox.com/developer/api-documentation/get-full-market-quote/
https://upstox.com/developer/api-documentation/get-market-status/

Only Python AST syntax was checked in preparation. Tests/network API calls have
NOT been executed locally. Run tests on your VM before this read-only collector.
The actual workspace remains PAUSED/SIMULATION_ONLY; no setting is changed.
