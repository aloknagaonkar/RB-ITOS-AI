# Combined quote stream and current-session observer

Run manage.py --repo "$PWD" --active-plan <current PLAN.json> --active-plan-sha256 <approved digest> --start-observer. Without --start-observer, only qualification is performed.

One command verifies the current closed runtime; runs 12 offline parser, feed-clock, depth and contract-basket tests on VM; exercises the installed Upstox MarketDataStreamerV3 in full mode for 35 seconds; requires all ten paired CE/PE ATM +/-2 contracts continuously fresh for at least five seconds; verifies runtime again; then starts a transient quote-only user unit for the remainder of today's session. A further running-cache and runtime check completes the batch. Existing service definitions, application source, policy, sealed release and plan are unchanged. No strategy evaluation, source journal consumption, database access by observer, enrollment, controller resume or order calls. The pinned release identity helper reads credentials in memory only. SDK output is suppressed to avoid recording authorized URLs.

The shared legacy integration.lock is acquired by both qualification and observer. Each real feed message supplies quote time; heartbeat/snapshot times cannot refresh stale instruments. Dropped messages are counted. Disconnect clears coverage, no stale quote is certified. No automatic reconnect; no complete fresh basket for 30 seconds stops the process. Systemd has Restart=no. Per-minute broker GET refresh resolves fresh NIFTY spot and current contracts. Basket membership changes update stream subscriptions. The observer periodically checks the release-manifest binding and original source PID command identity; a source restart/release change stops it.

Writes the explicitly requested quote snapshot at data/live-observation/hilega-strike-observation-v1/active-live-quotes.json, marked HILEGA_QUOTE_ONLY_OBSERVER_V1, and a separate quote-observer-status.json. Does not pretend to run the old collector; collector-status.json may remain historical. Copies the previous active cache into the private audit before starting. Does not write display subscription requests or old observation ledgers. Quote update files are atomic and owner-private. Only quote evidence is refreshed; no synthetic feeds or last-trade timestamps.

The transient unit hilega-quote-observer.service exits by 15:30 IST. It is not enabled for reboot or future sessions. This is current-session recovery, not completed operational automation. Stop explicitly with systemctl --user stop hilega-quote-observer.service. Startup failure requests stop; inspect audit RESULT.json, observer/STREAM-STATUS.json and observer/RESULT.json. If final runtime status fails after a successful start, the observer may still be running; inspect rather than rerun.

Coverage is verified for the concrete nearest-expiry ATM +/-2 basket, consistent with the five-strike CE/PE observation shape. This does NOT certify the production strategy's contract selection/admission, full-lot depth, spread limits, fee completeness, broker historical trade timezone, ownership or readiness to execute. The prior warmup-write prevention rollback remains unchanged and its integrated deployment is pending.

Eight-hour maximum and weekday 09:15..15:30 IST window; exchange holiday calendar is not independently certified. All callbacks are quote-only. No persistent trust material created or rotated.

Official SDK: https://upstox.com/developer/api-documentation/streamer-function/
Official V3 feed: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
Official option contracts: https://upstox.com/developer/api-documentation/get-option-contracts/

Local validation: static syntax, imports-by-inspection and ZIP integrity only. No behavioral tests run locally. VM qualification is mandatory before any managed publisher startup.
