# LIVE_OBSERVATIONAL_SHADOW_V1

Live-production **shadow observation only**. No broker order path exists.

Safety flags are frozen: `execution_enabled=false`, `paper_order_enabled=false`, `observation_only=true`.

## Auditable lifecycle

`OBSERVATION_DETECTED` -> `CANDLE2_CONFIRMED` -> `FUTURES_ALIGNMENT_CHECKED` -> `SPOT_LAG_CLASSIFIED` -> `OPTION_RESOLVED` -> `ENTRY_OPENED` -> repeated `RISK_STATE_UPDATED` -> `TRADE_CLOSED`.

Failures are explicit: `OBSERVATION_REJECTED` or `OBSERVATION_INCOMPLETE` with a reason.

Every event contains observation id, global sequence, timestamp, payload, previous hash and event hash. The JSONL log is the source of truth; the trade ledger and daily summary are derived from it.

## Frozen observational logic

- new opposite ALL_3 detected by the existing feature engine
- must survive candle 2
- futures OI alignment is recorded using the existing futures state engine
- spot classification: `SPOT_LAG` iff target-signed c1->c2 spot move <= 0
- exact moving ATM only
- bullish -> CE; bearish -> PE
- hypothetical entry = exact next-minute option open supplied by the live runtime adapter
- no nearest-strike or nearest-time fallback
- exit simulation = SL5, BE at +5%, trail after +10% with 3% distance, exact 15-minute time exit
- BE/trail changes become effective from the next 1-minute option bar
- 0.5 percentage-point research cost applied to net return

## What you can audit

Per observation: why detected, why confirmed/rejected, futures state, spot-lag classification, ATM/instrument, entry, every risk-state update, exit reason, exit price, MFE/MAE and final net result.

Daily: observations, trades closed, rejected/incomplete/open, winners/losers, cumulative net return %-points, best/worst trade, exit-reason counts, bullish/bearish counts, SPOT_LAG/already-moved counts.

## CLI

Verify hash chain:

```bash
python -m market_lab.live_observational_shadow_v1_cli verify --events data/live-observation/shadow-v1/events.jsonl
```

Build ledger:

```bash
python -m market_lab.live_observational_shadow_v1_cli ledger --events data/live-observation/shadow-v1/events.jsonl --output data/live-observation/shadow-v1/trade-ledger.csv
```

Daily summary:

```bash
python -m market_lab.live_observational_shadow_v1_cli daily-summary --events data/live-observation/shadow-v1/events.jsonl --session-date 2026-09-18 --output data/live-observation/shadow-v1/daily-2026-09-18.json
```

## Integration boundary

This package intentionally does not guess your current live-runtime/feed interfaces. Reuse the existing ALL_3 producer, futures OI state producer, exact ATM resolver and completed option 1-minute candles. The runtime adapter should call this shadow engine after those exact causal values are available.
