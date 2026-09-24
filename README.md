# Hilega session-centric replay + live availability integration

This patch changes Hilega Historical Replay from capture-folder selection to
trading-session selection.

## Session registry source precedence

1. `PHASE7D` — rich `hilega-phase7d-YYYY-MM-DD-*` evidence
2. `LIVE_SHADOW` — completed live Hilega audit day
3. `SESSION_REPLAY` — `hilega-milega-replay-v1/YYYY-MM-DD/step-audit.jsonl`
4. `RESEARCH_120` — 120-session research fallback

The UI presents one row/date per trading session and loads the richest available
evidence for that date.

## Automatic live -> historical availability

The API reads `data/live-observation/hilega-milega-v1/step-audit.jsonl`.
The current trading day is not listed as historical until its recorded strategy
state reaches `SESSION_LOCKED` / `SESSION_LOCKED_1455`.

After that record exists, the `/sessions` registry exposes the day automatically.
The frontend refreshes the session registry every 60 seconds and also provides a
manual Refresh sessions button.

No evidence is copied, rewritten or "promoted". Historical replay references the
existing immutable live audit directly.

## 120-session fallback

Dates found in:
`data/historical-evidence/hilega-milega-bullish-expansion-multisession-v1/`

are selectable even when no canonical per-day replay exists.

If only research summary data exists:
- entry/exit rows are shown,
- source is `RESEARCH_120`,
- evidence level is `SUMMARY`,
- exact candle conditions and CE lifecycle are explicitly unavailable.

If a richer Phase-7D/per-day/live audit exists for the same date it wins
automatically.

## Safety

- observation only
- no broker calls
- no worker starts/restarts
- no strategy changes
- no evidence mutation
- no order/paper-order behavior added

## Install

```bash
unzip hilega-session-centric-live-integration-patch.zip -d /tmp/

cd ~/RB-ITOS-AI
source .venv/bin/activate

python /tmp/hilega-session-centric-live-integration-patch/install.py   --repo "$PWD" --check
```

Only if CHECK PASS:

```bash
python /tmp/hilega-session-centric-live-integration-patch/install.py   --repo "$PWD" --apply

PYTHONPATH=backend pytest -q   tests/test_hilega_historical_ui_api_v1.py   tests/test_hilega_session_replay_api_v1.py

cd frontend
npm run build
```

Backend code changed, so the API process must be restarted after tests/build.
Do not use a broad `pkill` and do not restart the Hilega live worker just for
this API/UI change.

After the API is restarted, validate:

```bash
curl -s http://127.0.0.1:8123/api/live-shadow/hilega-historical/sessions   | python -m json.tool
```

Then load one session:

```bash
curl -s   'http://127.0.0.1:8123/api/live-shadow/hilega-historical/session?session_date=2026-09-23'   | python -m json.tool | head -100
```
