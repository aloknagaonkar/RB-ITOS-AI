# Combined replay display and input selection

No strategy engine, live coordinator, broker worker or rules changed. No tests/build were run locally. Run checks on the VM.

Changes: separate setup/qualified signal/entry times; explicit session-closed state at 14:55; readable performance colours; full 5m OHLC in replay rows; optional validated research artifact selection. Local cache remains the default. Validated mode reads exact saved artifacts from the two parity directories already created on your VM, requires passing research/live/shadow proof and matching engine implementation hashes, and never falls back silently. Existing artifacts and live audits are not rewritten. The local-versus-validated result comparison is also returned in API `input_comparison`, including trade prices/times.

The known Oct16 difference is between two input bases. This patch makes those visible/selectable; it does not assert which raw candle differs without comparing the VM files. The validated selection should show +68.30; local selection may retain +68.75.

Extract the ZIP in ~/RB-ITOS-AI, then:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python hilega-replay-ui-fix/install.py
.venv/bin/python hilega-replay-ui-fix/install.py --apply
PYTHONPATH=backend:. .venv/bin/python -m pytest -q tests/test_hilega_combined_replay_display.py tests/test_hilega_combined_promotion.py
npm --prefix frontend run build
bash scripts/restart_api_only.sh
```

Refresh with Ctrl+Shift+R. Select Combined, 16 October, then Replay inputs -> Validated research inputs. Check three trades, +68.30, distinct qualified time, and 14:55 SESSION CLOSED. Compare Local candle cache separately. The API-only restart preserves the live worker. Do not rerun the original promotion installer against these presentation changes.

Read-only API check:

```bash
curl -sS --get 'http://127.0.0.1:8123/api/live-shadow/hilega-historical/strategy-test' \
  --data-urlencode 'session_date=2026-10-16' --data-urlencode 'strategy=V2_ALIGN' \
  --data-urlencode 'input_basis=VALIDATED' \
  | .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({k:d.get(k) for k in ("strategy_version","manifest","performance_summary")},indent=2))'
```
