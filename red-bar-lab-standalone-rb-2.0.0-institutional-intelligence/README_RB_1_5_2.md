# RB-1.5.2 — Replay Data Source Resolver + Clean Readiness UX

RB-1.5.2 is a replay/data-fidelity stabilization release. It does not change live trading rules.

## Changes

- Historical replay resolves option data in this order:
  1. same-day ITOS `ONLINE` option-chain snapshots captured by the Dual Market Collector;
  2. expired-option historical one-minute candles;
  3. replay unavailable when neither source is sufficiently complete.
- Same-day live captures preserve point-in-time bid/ask, quantities, IV and Greeks when those fields were captured.
- Point-in-time replay never uses an option snapshot later than the replay timestamp.
- Live snapshot temporal coverage is measured against cached one-minute underlying timestamps.
- Research Lab shows replay source, live snapshot count, snapshot coverage and bid/ask availability.
- `Run Historical Decision Replay` is disabled when replay readiness is false.
- Expected replay-readiness conditions now render as warnings/information rather than Python tracebacks.
- Exit simulation can use the full captured option LTP snapshot series for same-day live-capture replay.

## Replay fidelity labels

- `LIVE_CAPTURE_PARITY_HIGH` — high temporal coverage from exact ITOS ONLINE option-chain captures.
- `LIVE_CAPTURE_PARTIAL` — usable same-day live captures with incomplete temporal coverage.
- `PARTIAL_LIVE_PARITY_HIGH` — high expired-option candle coverage; historical bid/ask/IV/Greeks unavailable.
- `PARTIAL_OPTION_REPLAY` — usable but incomplete expired-option coverage.
- `UNRELIABLE_LIVE_CAPTURE` / `UNRELIABLE_OPTION_REPLAY` — replay not ready.

## Validation

234 tests pass, including new tests proving live-capture source preference and no future-snapshot leakage.
