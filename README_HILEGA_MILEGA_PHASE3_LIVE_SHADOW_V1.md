# Hilega-Milega Phase 3 — Live Shadow Wiring V1

## Scope

This phase wires the already-validated canonical `HilegaMilegaBullishEngineV1`
into the existing live-shadow environment while preserving observation-only
safety and step-by-step auditing.

No broker order path is enabled. No option quantity logic is added. No strategy
rule is changed.

## Canonical strategy remains frozen

- RSI9
- EMA3(RSI9)
- WMA21(RSI9)
- Opening 09:15 / 09:20 / 09:25 path
- Path1 RSI-up-EMA arm
- Route A: same cross candle, RSI > 50 and RSI > WMA21
- Route B: armed and `(RSI > WMA21 OR EMA3 > WMA21)` and RSI rising and EMA rising
- Immediate RSI-down-WMA21 structural exit
- 14:55 hard cutoff

No WMA3/gap/3-candle/profit-management filters are introduced.

## Causal live timing

Historical chart-validation timestamps are 5-minute candle **start labels**.
Live decisions are only made after that candle has completed.

Example:

- 10:50 candle = minutes 10:50..10:54
- it becomes decision-eligible after 10:55
- audit keeps the signal bar label `10:50`

This prevents partial-candle/look-ahead behavior.

## 14:55 cutoff correction for live mode

The 14:55 rule is applied at the **start** of the 14:55 interval using the
14:55 one-minute OPEN. It is handled by `on_session_cutoff()` and does not feed
a partial 14:55 candle into RSI/EMA/WMA.

## Restart/bootstrap behavior

On startup/restart the live coordinator rebuilds the indicator and current-day
strategy state from:

1. prior historical NIFTY 1-minute sessions (45 calendar-day lookback), and
2. exact completed current-day 5-minute bars.

Bootstrap replay is not written into the live audit, so restart does not create
fake duplicate live decisions. Auditing is attached only after reconstruction.

Historical underlying data reuses the existing Hilega cache path.

## Live output paths

- `data/live-observation/hilega-milega-v1/step-audit.jsonl`
- `data/live-observation/hilega-milega-v1/data-health.jsonl`

The step audit remains append-only and hash chained.

## API endpoints

- `GET /api/live-shadow/hilega-milega/status`
- `GET /api/live-shadow/hilega-milega/decision-audit`
- `GET /api/live-shadow/hilega-milega/transitions`

These are additive. Legacy ALL3 live-shadow endpoints remain available.

## Worker strategy selection

The existing `market_lab.live_shadow_worker_v1` now supports both engines.
The default is Hilega-Milega:

```bash
LIVE_SHADOW_STRATEGY=HILEGA_MILEGA_BULLISH_SHADOW_V1
```

Legacy rollback remains available:

```bash
LIVE_SHADOW_STRATEGY=LEGACY_ALL3
```

## Safety

Hard flags remain:

- `observation_only = true`
- `execution_enabled = false`
- `paper_order_enabled = false`

No broker order is created by Phase 3.

## Validation

Run:

```bash
python -m pytest \
  tests/test_hilega_milega_strategy_v1.py \
  tests/test_hilega_milega_historical_replay_v1.py \
  tests/test_hilega_milega_live_shadow_v1.py \
  tests/test_live_shadow_step_audit_v1.py -v
```

Expected: `24 passed`.

Regression checks:

```bash
python -m pytest \
  tests/test_live_shadow_ui_v1.py \
  tests/test_live_shadow_production_wiring_v1.py -v
```

Expected: `6 passed`.

## First live-shadow run

Load credentials and explicitly select the new strategy:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
set -a
source .env
set +a
export LIVE_SHADOW_STRATEGY=HILEGA_MILEGA_BULLISH_SHADOW_V1
python -m market_lab.live_shadow_worker_v1
```

In another terminal:

```bash
tail -f data/live-observation/hilega-milega-v1/data-health.jsonl
```

and:

```bash
tail -f data/live-observation/hilega-milega-v1/step-audit.jsonl
```

Do not proceed to paper/broker execution from this phase. First review live
signal timestamps, indicator values, reasons, transitions, restart behavior,
and the 14:55 cutoff against the historical/research semantics.
