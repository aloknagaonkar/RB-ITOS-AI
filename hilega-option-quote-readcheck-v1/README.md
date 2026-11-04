# Bounded option quote read check

Runs eight offline parser/identity tests on the VM, verifies current closed rollout status before/after, reads credentials using the already pinned current worker identity helper and verifies immutable release and closed gate. Uses at most five broker GET calls: underlying full quote, NIFTY option contracts, then three full-quote snapshots two seconds apart. Fixed endpoints only, no redirects or permission-error retry. Tokens/provider error text are never printed. GET bodies and detailed result are saved in a new owner-private audit folder, not active market caches. No databases, services, source, subscriptions or policy are changed. No execution code is invoked.

Selects nearest nonexpired expiry and five paired strikes centered on nearest listed strike to fresh NIFTY spot: ten contracts. Exact token coverage, underlying metadata, lot size, positive last price, fresh quote timestamp (0..10 seconds), two-sided uncrossed book and positive bid/ask depth are checked in all three snapshots. This is a diagnostic basket, not approval of deployed strategy selection, spread/premium/depth admission thresholds, or sufficient depth for a full lot. Last trade age is reported separately and is not certified fresh by the quote check.

Accepts timezone-aware ISO quote timestamps and explicit epoch milliseconds; rejects naive timestamps and does not shift them. This does not resolve historical trade timestamp semantics. Session-window check uses weekdays 09:15..15:30 IST and does not certify exchange holiday schedules.

A successful result is bounded REST evidence only. It does not restore continuous publisher/SDK WebSocket, replace active-live-quotes.json, or enable trading. Current runtime status subprocesses are called without a held maintenance lock. Errors save partial evidence when inside capture; inspect BEFORE.json, AFTER.json or TESTS.json for prerequisite failures. No automatic retry/rollbacks.

Official contracts: https://upstox.com/developer/api-documentation/get-option-contracts/
Official quotes: https://upstox.com/developer/api-documentation/get-full-market-quote/
The V2 quote docs show ISO offset timestamps in the example while describing milliseconds; both explicit formats are supported, never guessed naive wall clocks.

Local verification: syntax and ZIP integrity only. Behavioral tests and broker capture run on VM.
