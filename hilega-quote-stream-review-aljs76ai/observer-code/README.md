# Combined quote stream and current-session observer

Run manage.py --repo "$PWD" --active-plan <current PLAN.json> --active-plan-sha256 <approved digest> --start-observer. Without --start-observer, only qualification is performed.

One command verifies the current closed runtime; runs 21 offline parser, feed-clock, depth and contract-basket tests on VM; exercises the installed Upstox MarketDataStreamerV3 in full mode for 35 seconds; requires all ten paired CE/PE ATM +/-2 contracts continuously fresh for at least five seconds; verifies runtime again; then starts a transient quote-only user unit for the remainder of today's session. A further running-cache and runtime check completes the batch. Existing service definitions, application source, policy, sealed release and plan are unchanged. No strategy evaluation, source journal consumption, database access by observer, enrollment, controller resume or order calls. The pinned release identity helper reads credentials in memory only. SDK output is suppressed to avoid recording authorized URLs.

The shared legacy integration.lock is acquired by both qualification and observer. Each real feed message supplies quote time; heartbeat/snapshot times cannot refresh stale instruments. Dropped messages are counted. Disconnect clears coverage, no stale quote is certified. No automatic reconnect; no complete fresh basket for 30 seconds stops the process. Systemd has Restart=no. Per-minute broker GET refresh resolves fresh NIFTY spot and current contracts. Basket membership changes update stream subscriptions. The observer periodically checks the release-manifest binding and original source PID command identity; a source restart/release change stops it.

Writes the explicitly requested quote snapshot at data/live-observation/hilega-strike-observation-v1/active-live-quotes.json, marked HILEGA_QUOTE_ONLY_OBSERVER_V1, and a separate quote-observer-status.json. Does not pretend to run the old collector; collector-status.json may remain historical. Copies the previous active cache into the private audit before starting. Does not write display subscription requests or old observation ledgers. Quote update files are atomic and owner-private. Only quote evidence is refreshed; no synthetic feeds or last-trade timestamps.

The transient unit hilega-quote-observer.service exits by 15:30 IST. It is not enabled for reboot or future sessions. This is current-session recovery, not completed operational automation. Stop explicitly with systemctl --user stop hilega-quote-observer.service. Startup failure requests stop; inspect audit RESULT.json, observer/STREAM-STATUS.json and observer/RESULT.json. If final runtime status fails after a successful start, the observer may still be running; inspect rather than rerun.

Coverage is verified for the concrete nearest-expiry ATM +/-2 basket, consistent with the five-strike CE/PE observation shape. This does NOT certify the production strategy's contract selection/admission, full-lot depth, spread limits, fee completeness, broker historical trade timezone, ownership or readiness to execute. The prior warmup-write prevention rollback remains unchanged and its integrated deployment is pending.

Eight-hour maximum and weekday 09:15..15:30 IST window; exchange holiday calendar is not independently certified. All callbacks are quote-only. No persistent trust material created or rotated.

Official SDK: https://upstox.com/developer/api-documentation/streamer-function/
Official V3 feed: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
Official option contracts: https://upstox.com/developer/api-documentation/get-option-contracts/

Local validation: static syntax, imports-by-inspection and ZIP integrity only. No behavioral tests run locally. VM qualification is mandatory before any managed publisher startup.

## v2: explicit session deferral

Runs 21 offline tests on the VM, then checks the IST session window BEFORE runtime checks, credential loading, broker GETs or SDK connection. Outside the weekday 09:15..15:30 clock window, returns QUOTE_STREAM_VALIDATION_DEFERRED_OUTSIDE_USABLE_SESSION with a reason (weekend, before open, after close). Also defers when less than three minutes remain for the batch. This is a validation timing guard, not a change to strategy entry/cutoff rules. The worker repeats a session preflight before loading credentials and making requests. No holiday schedule is assumed verified. No retries are scheduled automatically.

An after-hours run passes offline tests but does NOT pass live quote validation or start a service. It saves only its new private audit. Run the same command in an open trading session for WebSocket qualification. Freshness thresholds remain unchanged. Session ending during an observer run is recorded as QUOTE_OBSERVER_SESSION_ENDED rather than a successful current quote qualification.

## v3: successor compatibility and milestone check

Use the installed warmup successor plan hilega-warmup-install-plan-6d56keoy/PLAN.json and its SHA 25a6a37a1600b1a0cebb5026abd356712e9d764b048a4ae757a5c5c475d1f3f9. The exact approved status driver is hilega-warmup-prevention-deploy-v1/manage.py. Its package bytes and manifest are pinned; arbitrary plan-selected commands cannot be executed. The predecessor registration status route is no longer used.

Runs 21 offline tests on VM. Validates successor runtime even after hours, then explicitly defers before credential loading, broker GETs or websocket use. An after-hours run therefore gives current closed-runtime/milestone evidence plus a clear session deferral, without starting an observer. Each successful/deferred batch creates its own MILESTONES.md in the new audit; it does not overwrite the deployment plan's milestone file. Earlier REST evidence is identified as earlier, not refreshed. WebSocket and production strategy coverage remain unchecked unless actually qualified; production admission remains unverified even after diagnostic basket qualification.

Existing stream and session behavior is otherwise retained. No live application code, dependency manifests, active plan or current service definitions are changed by qualification. --start-observer still controls transient current-session publishing after real stream qualification passes. Warmup prevention remains deployed; this package does not revert it.

## v4: native contract selector alignment

Supersedes v3 for the pending reminder and next open-session run. Runs 27 VM cases (21 previous plus six native-selection cases). Worker loads the exact installed hilega-production-contract-preview/rules.py from the verified immutable release, requires SHA 660c92d979626692898c4b154b3918be24ed6fe27424885f165ccd7ee45195e5, and calls its select function with offsets [-2,-1,0,1,2], one lot, and the actual session date. Exact midpoint ties choose HIGHER_STRIKE; grid spacing and minimum lot/freeze/tick checks are native, not approximated with a second algorithm. Selected metadata and native offsets/quantity are preserved in snapshots. A packaged reference copy is used only by offline tests, and its hash must match the reviewed native module. Production uses the installed copy, never the test reference.

No installed production rules, limits, manifests, plans or service definitions are edited. This corrects the diagnostic observer, not production policy. Positive/fresh quotes alone still do not certify production admission, full-lot liquidity, cash/risk rules or ownership. Live feed qualification remains pending until the open-session run. After-hours validation still checks closed runtime and defers without credentials or broker access.
