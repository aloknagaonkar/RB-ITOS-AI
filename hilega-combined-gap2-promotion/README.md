# Combined gap2/WMA2 live + replay promotion

Prepared against the supplied ZIP commit `88bb192d092b8915a7f2f72a31d35ac5df77b770`. See CHANGES.md for component-by-component dependencies and rules. No local Python/tests/build were run. VM validation is required before activation. The package never submits orders or starts services.

## 1. Extract and check

Extract `hilega-combined-gap2-promotion.zip` in `~/RB-ITOS-AI`. It creates `hilega-combined-gap2-promotion/`.

```bash
cd ~/RB-ITOS-AI
.venv/bin/python hilega-combined-gap2-promotion/install.py --check
.venv/bin/python hilega-combined-gap2-promotion/install.py \
  --stage data/research/hilega-combined-candidate
```

If source hashes differ, stop and share the exact filename; do not force overwrite local changes. If the stage directory already exists, choose a new name consistently below.

## 2. Validate staged code without changing running services

```bash
cd ~/RB-ITOS-AI
(
set -e
STAGE="$PWD/data/research/hilega-combined-candidate"
PYTHONPATH="$STAGE/backend:$PWD" .venv/bin/python -m pytest -q \
  "$STAGE/tests/test_hilega_combined_promotion.py" \
  "$STAGE/tests/test_hilega_alignment_dual_exit_live_v1.py" \
  tests/test_hilega_sandbox_event_bridge_v1.py \
  tests/test_hilega_execution_dispatch_validation.py \
  tests/test_hilega_strike_selector_v1.py

npm --prefix "$STAGE/frontend" run build

PYTHONPATH="$STAGE/backend:$PWD" .venv/bin/python \
  "$STAGE/scripts/validate_hilega_combined_promotion.py" \
  --reference-root data/research/hilega-bearish-ema30-oct-through16 \
  --output data/research/hilega-combined-parity-historical

PYTHONPATH="$STAGE/backend:$PWD" .venv/bin/python \
  "$STAGE/scripts/validate_hilega_combined_promotion.py" \
  --date 2026-10-16 \
  --session-input data/research/hilega-pending-previous10-plus-today-20261016/captured-nifty-1m.json \
  --apply-recorded-overrides \
  --reference-root data/research/hilega-bearish-ema30-oct-through16 \
  --output data/research/hilega-combined-parity-oct16
)
```

Parity uses only local cached research inputs. It first reproduces the frozen original baseline, then compares actual combined trades and full live/replay entry/exit event identities. It also verifies the live adapter calls option shadow entry/exit only for the accepted strategy events, with option operations intercepted so no market-data or broker calls occur. It does not claim provider fill validation.

The October16 control used mixed recorded/API inputs. If its input baseline does not match, stop: supply the exact captured/recorded-session input that produced the control, rather than bypassing parity. Do not relax the comparison. The expected eleven-session combined total is +1016.30 gross NIFTY points, but exact trade parity is required in addition to the total.

## 3. Install only after VM validation passes, while flat

Prefer activation for the next session. Never switch a running open strategy or unresolved sandbox orders. First inspect the existing worker:

```bash
bash scripts/status_hilega_upstox_sandbox_worker.sh
```

Only if open legs, pending fills and uncertain requests are all zero:

```bash
cd ~/RB-ITOS-AI
(
set -e
bash scripts/stop_hilega_upstox_sandbox_worker.sh
bash scripts/stop.sh
.venv/bin/python hilega-combined-gap2-promotion/install.py --apply \
  --validation data/research/hilega-combined-parity-historical/validation.json \
  --validation data/research/hilega-combined-parity-oct16/validation.json
npm --prefix frontend run build
bash scripts/restart.sh
)
```

The installer checks flatness, stopped processes, source hashes and exact implementation hashes in parity proofs, creates a timestamped backup, and copies only listed files. It does not edit `.env`, approval policies, controls, orders or journals. A failed installation rolls back files already copied. It does not automatically start the sandbox basket worker.

New sandbox BUYs require an arm containing the promoted strategy version. Existing EXIT reconciliation remains available. Rearm through the existing daily/manual sandbox process while flat; do not reuse a prior-policy arm. Ranked sandbox modes need the strike policy reviewed for version `bullish-gap2-full-wma2-1.0.0`; old approval is intentionally not rewritten. Keep real-money execution disabled.

## 4. Review after restart

```bash
curl -sS 'http://127.0.0.1:8123/api/live-shadow/hilega-directional/status?fast=true' \
  | .venv/bin/python -m json.tool
curl -sS --get 'http://127.0.0.1:8123/api/live-shadow/hilega-historical/strategy-test' \
  --data-urlencode 'session_date=2026-10-14' \
  --data-urlencode 'strategy=V2_ALIGN' \
  | .venv/bin/python -m json.tool
```

Use the route shown by your API's OpenAPI if the historical prefix differs. The frontend selector formerly called V2 alignment now names the combined strategy. New replay artifacts live under `data/historical-evidence/hilega-combined-gap2-full-wma2-v1`. Old baseline replay remains in the original module and is available through `strategy=V2_ALIGN_LEGACY`; original recorded audit rows retain original versions.

Confirm policy ID/version, five-minute decision cadence, signal-qualified versus entry separation, touch-wait evidence, gap2/full WMA2 details and shadow timestamps. Non-boundary `COMBINED_PRICE_OBSERVATION` rows are price-only inputs for velocity observation, not strategy decisions or trade signals.

## If any gate fails

Share the first traceback or mismatch. Do not restart the updated worker, force the installer, alter reference results or remove pending-order state. The implementation has not been validated until these VM checks pass.
