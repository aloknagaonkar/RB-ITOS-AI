# LIVE_SHADOW_PRODUCTION_WIRING_V1

Runs alongside the existing `market_lab.worker`; it does not replace or modify the collector.

The existing collector remains the source of option-chain `Snapshot` rows in `lab.db`. At each 5-minute exchange checkpoint, the shadow worker selects the **first causally available snapshot at or after the checkpoint**, limited to 30 seconds. The checkpoint label and actual `received_at` are both retained, so latency is auditable rather than hidden.

Futures and selected-option candles reuse Upstox intraday endpoints already present in this repository:
- `/v3/historical-candle/intraday/{instrument}/minutes/5`
- `/v3/historical-candle/intraday/{instrument}/minutes/1`

Futures 5-minute timestamps are interval starts; V1 labels causal availability at start + 5 minutes. The next-minute option OPEN remains a hypothetical research execution proxy: V1 waits for that minute to complete, then records its OPEN. No broker order is created.

Restart safety:
- deterministic observation IDs;
- state reconstructed from the append-only event log;
- option minute continuity resumes from `last_bar_timestamp`;
- no broker/order module imported.

Outputs:
- `data/live-observation/shadow-v1/events.jsonl`
- `data/live-observation/shadow-v1/data-health.jsonl`

After tests pass and the existing collector is running, start with:
`python -m market_lab.live_shadow_worker_v1`

Observation only. Do not run a second copy of this shadow worker.
