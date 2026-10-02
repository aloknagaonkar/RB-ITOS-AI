# Hilega-Milega Phase 2 — Historical Multi-Session Replay + Decision Audit

## Scope

This phase connects the canonical `HilegaMilegaBullishEngineV1` to a dedicated
historical multi-session replay path. It does **not** connect the strategy to
live shadow yet and does **not** enable broker execution.

## Important parity correction

The validated research replays compare RSI/EMA/WMA transitions only within the
current trading session. Indicator values are warmed continuously using prior
sessions, but a Path1 cross is not allowed to compare the prior day's final bar
with today's 09:15 bar.

Phase 2 therefore resets only `previous_indicators` / `previous_bar` at a session
boundary while preserving the streaming indicator engine. This prevents an
overnight 09:15 false Path1 cross and matches the validated per-session replay
semantics.

## New replay modules

- `backend/market_lab/hilega_milega_historical_replay_v1.py`
- `backend/market_lab/hilega_milega_historical_replay_cli_v1.py`

The replay:
- uses official Upstox NIFTY 1-minute historical candles;
- creates exact 5-minute bars from exactly five 1-minute candles;
- fails on partial 5-minute candles;
- caches fetched underlying candles;
- warms RSI/EMA/WMA using prior sessions;
- runs the exact canonical strategy engine on requested target sessions;
- preserves the 14:55 hard cutoff;
- remains observation-only.

## Audit outputs

For each replayed session:

- `step-audit.jsonl` — existing hash-chained machine audit
- `trades.csv`
- `signal-decision-audit.csv`
- `signal-decision-audit.json`
- `signal-decision-audit.txt`

The decision audit explains WHY a candidate entered, remained armed, was
rejected/waiting, structurally exited, or was closed/cancelled by 14:55.

It records:
- RSI9 / EMA3(RSI) / WMA21(RSI)
- previous indicator values
- RSI↑EMA cross
- RSI↓WMA cross
- RSI > 50
- RSI > WMA
- EMA > WMA
- RSI rising
- EMA rising
- FULL opening alignment
- Route A eligible/pass/fail reasons
- Route B eligible/pass/fail reasons
- state before / after
- emitted events
- final human-readable decision reason

Combined outputs:
- `multi-session-summary.json`
- `multi-session-sessions.csv`
- `multi-session-trades.csv`
- `multi-session-signal-decision-audit.csv`

## Safety

- `execution_enabled = false`
- `paper_order_enabled = false`
- `observation_only = true`
- no option order is created
- no broker execution path is invoked

## Validation command

```bash
python -m pytest \
  tests/test_hilega_milega_strategy_v1.py \
  tests/test_hilega_milega_historical_replay_v1.py \
  tests/test_live_shadow_step_audit_v1.py -v
```

Expected for this bundle: `20 passed`.

## Six-session replay

```bash
set -a
source .env
set +a

python -m market_lab.hilega_milega_historical_replay_cli_v1 \
  --dates \
    2026-09-11 \
    2026-09-15 \
    2026-09-16 \
    2026-09-17 \
    2026-09-18 \
    2026-09-21
```

Do not use `--refresh-cache` unless you intentionally want to refetch historical
underlying candles.

## Next gate

Do not wire the engine into live shadow until the six-session replay is reviewed
signal-by-signal and the audit explains every entry, wait/rejection, exit, and
14:55 action.
