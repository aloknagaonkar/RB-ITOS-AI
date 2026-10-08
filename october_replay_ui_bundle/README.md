# October 6–7 recovered replay UI and expiry rollover

This bundle surgically patches the installed source. It does not replace later
forward-publisher fixes, change strategy rules, submit orders or fabricate live audits.

Local validation: 53 regression tests passed, frontend production build passed,
and offline API publication/readback passed for both dates. The VM must still
run its own installer checks. Expected snapshot results: Oct6 V1 -111.35 points,
V2 -107.15; Oct7 V1 -22.90, V2 +32.50. If installed strategy versions differ,
recomputed results may differ. This is not a recorded-live comparison.

Run from the repository root:

```bash
source .venv/bin/activate
python october_replay_ui_bundle/install.py &&
PYTHONPATH=backend:. python scripts/publish_october_recovered_replay.py --confirm PUBLISH_RECOVERED_REPLAY_ONLY &&
./scripts/restart.sh &&
./scripts/status.sh
```

Select October 6 or 7 in Hilega Historical Replay, then V1 or WMA-gap V2.
For Midpoint select Historical replay and the same date. Reconstructed evidence
is labelled RECOVERED HISTORICAL REPLAY, not recorded-live or untouched forward.
Existing live views remain independent. The publisher refuses to overwrite an
existing `data/recovery/october-2026/ui-replay` directory.

The bundled inputs are the previously supplied broker-recovered candles and
warmup caches. Replays run with the installed canonical/research engines and
Midpoint's configuration loaded from `.env`. Replayed prices are NIFTY points,
not option premium P&L or broker fills. No fees/slippage assumed. Midpoint input
omits futures_open: unavailable health conditions must not be interpreted as PASS.

Expiry: `HILEGA_OPTION_EXPIRY_MODE` defaults to AUTO. AUTO ignores the old
`HILEGA_MILEGA_OPTION_EXPIRY` fixed date and uses instrument search each session,
including when evidence recording is disabled. MANUAL is an explicit override
and rejects expired dates. API/token/data errors still require attention; no
contract is invented. Sandbox already selects nearest unexpired CE/PE on ENTRY
and reuses the original contract on EXIT. This patch does not modify sandbox
execution or arming, and does not enable live trading. Futures expiry is separate.

After publication, verify:

```bash
curl -fsS 'http://127.0.0.1:8123/api/live-shadow/hilega-historical/strategy-test?session_date=2026-10-06&strategy=V1' -o /tmp/oct6-v1.json
python -c 'import json; x=json.load(open("/tmp/oct6-v1.json")); print(x["evidence_cohort"],x["report_count"],x["performance_summary"])'
```

V1 contains all 75 completed candle decisions, indicator values and emitted
events. V2 includes the existing per-minute confirmation inspection and trade
results. Midpoint preserves strategy event order and health columns. These
recovery artifacts cannot prove what the live worker actually decided on Oct6/7.
