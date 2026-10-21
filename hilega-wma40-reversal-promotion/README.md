# Promote tested bearish WMA40 + confirmed bullish reversal

Policy ID stays BULLISH_GAP2_FULL_WMA2 for existing routing compatibility.
Version changes to bullish-gap2-full-wma2-2.0.0-wma40-reversal.
No tests, Python strategy execution, or builds have been run locally.

## Rules

Completed5m bearish exit: original RSI9>WMA21 AND EMA3 of RSI9>WMA21 AND WMA21>40,
or fully confirmed bullish entry, whichever first. At equality40 keep holding.
No exit latch. Opposite monitor starts after bearish entry and checks normal
bullish signal/followup rules while bearish remains active. It never opens a
second position. Signal or arm alone cannot reverse. At reversal, close bearish
first, then emit bullish entry at the same strategy boundary. Existing broker
fill/position safeguards are not bypassed or changed.

All entry requirements, bullish gap>=2/full WMA>=2, bullish normal dual exit,
manual reset, execution mode, subscription/P&L polling and14:55 cutoff retained.
Manual reset/cutoff clears the opposite monitor. It is reconstructed from the
same completed bars on live bootstrap, like other strategy state.

## Components

- Shared policy used by live and replay: normal WMA exit permission and atomic
  reversal events; no runtime research imports, exec or source compilation.
- Live/replay audit: original dual exit versus final normal permission, WMA40
  pass, final action, bullish monitor setup/followup checks and reversal reason.
- Candle projection/overlay and inspection: recorded new fields available in UI.
- Replay inspection: no longer labels a bearish dual exit alone as EXIT.
- Validated replay uses the newly generated proof/artifacts. Old proof/data are
  retained and cannot silently claim parity for the new version. Local replay
  cache fingerprint changes automatically with source version/hash.
- Existing shadow dispatch remains exit-first; validator checks exact callback
  entries/exits, research trades and live/replay event parity.
- Sandbox bridge/order/fill-ledger code is untouched, as are live broker flags.

## 1 — Stage and validate on Ubuntu VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-wma40-reversal-promotion.zip
.venv/bin/python hilega-wma40-reversal-promotion/install.py --check
.venv/bin/python hilega-wma40-reversal-promotion/install.py \
  --stage data/research/hilega-wma40-candidate

STAGE="$PWD/data/research/hilega-wma40-candidate"
PYTHONPATH="$STAGE/backend:$PWD" .venv/bin/python -m pytest -q \
  "$STAGE/tests/test_hilega_wma40_promotion.py" \
  tests/test_hilega_combined_promotion.py \
  tests/test_hilega_sandbox_event_bridge_v1.py \
  tests/test_hilega_execution_dispatch_validation.py

npm --prefix "$STAGE/frontend" run build

PYTHONPATH="$STAGE/backend:$PWD" .venv/bin/python \
  "$STAGE/scripts/validate_hilega_wma40_promotion.py" \
  --input-zip data/research/hilega-bearish-exit-input-20261021/timing-input.zip \
  --reference-root data/research/hilega-bearish-wma40-exit-september \
  --reference-root data/research/hilega-bearish-wma40-exit-oct-through21 \
  --output data/research/hilega-wma40-promotion-parity
```

The second parity command replays34 saved sessions; runtime can be several minutes.
Do not proceed if tests/build/parity fail. Share output first. Missing/changed
source anchors are an intentional stop, not permission to overwrite local fixes.
The installer writes only staged files until --apply. No strategy worker restarts
or sandbox orders occur during staging/parity. Do not point staged backend at
a running live service; it is only for offline tests and validation.

## 2 — Apply only after PASS

Share stage results first. Apply requires proof including Sep25, Sep29, Oct8,
Oct12, Oct19 and Oct21. Before service restart confirm the sandbox ledger is
flat and no unresolved actual demo exposure exists. Do not force-clear state.

When ready, stop affected strategy/observer/API services using existing managed
scripts, apply, rebuild production frontend, then restart managed services.
Do not stop a worker responsible for unresolved broker positions/orders.

```bash
.venv/bin/python hilega-wma40-reversal-promotion/install.py --apply \
  --validation data/research/hilega-wma40-promotion-parity/validation.json
npm --prefix frontend run build
```

Installer creates a timestamped source backup/receipt and rolls back copied
source files on failure. It does not start/stop services, arm sandbox, clear
journals, rewrite old evidence, or enable production broker execution.
Source rollback is possible from backup; strategy-state recovery still needs
normal existing bootstrap/reconciliation. Source hashes must match the supplied
latest ZIP; newer local modifications require review before applying.

## UI validation after restart

Current strategy version must end wma40-reversal. Live decision candle inspection
shows WMA>40 permission, HOLD_WMA_LE40, and opposite monitor evidence. A reversal
shows bearish exit then bullish entry. Replay LOCAL recalculates available saved
dates; VALIDATED shows exact new proof inputs for dates in the parity report.
Missing local candles remain unavailable; old research is not substituted.
Actual live API market data and sandbox fills are not validated by offline parity.
