Hilega PCR inspection v2

Install from repository root:
source .venv/bin/activate
python hilega_pcr_inspection_bundle_v2/install.py && ./scripts/restart.sh

If PCR collection has not been enabled, run afterwards:
python hilega_pcr_inspection_bundle_v2/enable_collection.py

This setup command configures Upstox, ±5 wings and the current Hilega expiry once, preserving the existing morning anchor and intervals, then enables the local PCR collector. It does not alter Hilega rules or submit orders. PCR expiry does not automatically follow Hilega rollover; rerun setup when expiry changes. Fixed baseline may be absent before anchor; classification requires prior observations. Review Sandbox worker status following restart, as its startup is separate.

UI:
- Hilega shadow: two compact total summaries, fixed and moving ATM, with PCR, CE/PE summed OI change %, aggregate positioning, combined bias. Expand each for strike PCR, OI change %, classifications and combined bias.
- Active shadow and active Sandbox legs: one new column, Combined bias at that exact strike and retained contract expiry, requiring matching contract identity. Closed Sandbox trades do not get this new live column. No active PCR/OI columns added.
- Selected candle audit only: PCR card on expansion, joins persisted same-session Upstox evidence available by the candle decision boundary. Missing/stale observations remain unavailable. No later evidence or current-day substitutions into old candles. Card does not create historical PCR for sessions where it was not collected.

Classification uses the existing 5/15/30-minute positioning engine, including its neutral thresholds. Price/OI: +/+ long buildup, -/+ short buildup, -/- long unwinding, +/- short covering. PCR = summed PE OI / summed CE OI. OI percentages compare sums for the same selected contracts, never average percentages or substitute different moving-window contracts.

Combined bias per strike: CE long buildup or short covering supports bullish; CE short buildup or long unwinding supports bearish. PE directions are reversed. Conflicting nonzero evidence MIXED; both neutral NEUTRAL; missing leg UNAVAILABLE. A neutral side does not oppose the other available side.
Aggregate: classifications weighted by absolute observed OI change; 60% dominance needed for a side classification or directional bias, otherwise MIXED. This is an explicitly unvalidated diagnostic heuristic, not a price trend predictor or trade filter.

Audit default 5-minute horizon; no evidence received/persisted after decision, including late baselines. Current contexts require observations no older than 120s. Reconstructed historical records published later are not presented as knowledge available at a past decision. Retained database observations support the inspection; this release does not append PCR into the immutable strategy journal. Exact contracts outside the collector catalog return UNAVAILABLE instead of another strike or expiry.

Validation: 49 tests passed, frontend TypeScript/Vite build passed. Installer preflights patch anchors and backs up/restores source plus dist on validation failure. No broker calls or order/strategy configuration changes during install. Data collection must be verified on the VM during market hours.
