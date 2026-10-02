# Phase 7D.1 — acquisition correction (offline patch)

This is a patch against the ZIP supplied in this conversation; it is not a live VM deployment or a claim of recorded-session parity. Inspect your VM working tree and compare versions before applying. Do not overwrite newer VM changes.

## Changed files

- `backend/market_lab/gateways.py`: current-session intraday, active contract catalog, active option historical candles.
- `backend/market_lab/hilega_milega_functional_parity_replay_v1.py`: exact session validation, explicit source selection, exact CE identity, causal option-minute visibility and fail-closed empty replay.
- `backend/market_lab/hilega_milega_phase7d_historical_capture_v1.py`: manifest source, counts/timestamps/hashes, option coverage, selected candidate baskets.
- `backend/market_lab/hilega_milega_live_shadow_v1.py`: remove warmup-session strategy state before applying target-day bars; retain indicator warmup.
- `tests/test_hilega_phase7d1_acquisition_v1.py`: new source-selection and fail-closed regression tests.
- `tests/test_hilega_milega_functional_parity_replay_v1.py`: mocks updated for explicit current-session API.
- `tests/test_hilega_milega_phase7c_pending_exit_v1.py`: mocked exact contract/intraday gateway updated.

## VM workflow

```bash
cd ~/RB-ITOS-AI
git status --short
git branch --show-current
# Confirm feature/pcr-foundation and resolve unrelated uncommitted changes first.
# Transfer the patch ZIP to the VM, unzip in a TEMP directory and DIFF each source.
mkdir -p /tmp/hilega-phase7d1
unzip -o ~/hilega-phase7d1-patch.zip -d /tmp/hilega-phase7d1
for f in backend/market_lab/gateways.py \
         backend/market_lab/hilega_milega_functional_parity_replay_v1.py \
         backend/market_lab/hilega_milega_phase7d_historical_capture_v1.py \
         backend/market_lab/hilega_milega_live_shadow_v1.py; do
    diff -u "$f" "/tmp/hilega-phase7d1/$f" || true
done
# AFTER inspecting and reconciling differences, copy only the approved files.
# Avoid running the live-worker restart script for an offline capture.
source .venv/bin/activate
PYTHONPATH=backend python -m pytest -q \
  tests/test_hilega_phase7d1_acquisition_v1.py \
  tests/test_hilega_milega_functional_parity_replay_v1.py \
  tests/test_hilega_milega_real_session_parity_v1.py \
  tests/test_hilega_milega_phase7c_pending_exit_v1.py \
  tests/test_hilega_milega_live_shadow_v1.py
```

## Capture (new directory; do not overwrite old evidence)

```bash
python -m market_lab.hilega_milega_phase7d_historical_capture_v1 \
  --session-date 2026-09-23 --expiry 2026-09-29 \
  --output-root data/historical-evidence/hilega-phase7d-2026-09-23-d1
```

The current-day intraday endpoint is used only when the target session equals acquisition date in IST. On a later day this command deliberately uses the historical endpoint; a previously captured Sep 23 intraday response cannot be recovered from today's intraday endpoint. If the broker still returns no usable historical data, the capture must return UNAVAILABLE. The ZIP does not include live broker credentials or historical response caches.

## Validation

59 targeted tests passed offline against the attached ZIP snapshot. A complete repository test run, VM test, actual Sep 23 historical capture, historical/live parity comparison and natural live exit verification were NOT performed. Keep execution and paper orders disabled.
