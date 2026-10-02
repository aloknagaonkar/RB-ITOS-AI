# Production Paper Trading Foundation V1

This phase establishes the production-safe persistence and process foundation for paper trading.

## Hard invariants

- Browser independence: the paper service is a standalone process.
- Paper state is stored in the same SQLAlchemy database used by the platform.
- Maximum open positions: 4, enforced from the database.
- Maximum holding time: none.
- Live broker execution: structurally disabled.
- Entry fill basis: ASK for long-option paper buys.
- Exit/mark basis: BID for long-option paper exits.
- Every signal stage and position transition is journaled.
- Signal replay is idempotent.
- Service restart reloads open positions from the database.
- Four open positions never cause eviction of an existing trade.

## Tables

`paper_control`
- manual paper enable/disable
- live_enabled is always forced false
- max_open_positions fixed at 4

`paper_signals`
- WAIT_P2 / CONFIRMED / REJECTED lifecycle
- P1/P2 observation ids
- immutable-ish evidence journal payload
- dedupe key

`paper_positions`
- exact option identity
- entry/exit execution evidence
- independent SL/BE/trailing state
- no time-exit field

`paper_events`
- PASS / FAIL / WAITING / SKIPPED-ready event journal
- stage + reason code + input/output evidence

`paper_health`
- standalone service heartbeat / recovery status

## Important

This phase does NOT yet evaluate OI/PCR/VWAP and does NOT place paper entries from market data.
It is the production foundation that the live strategy input pipeline will call in Phase P2/P3.

Do not enable paper mode merely because these tests pass.

## Manual control

Initialize:

```bash
python -m market_lab.paper_control_v1 init
```

Quick status:

```bash
python -m market_lab.paper_control_v1 status
```

Detailed audit:

```bash
python -m market_lab.paper_control_v1 detail --limit 250
```

The future manual enable command is intentionally explicit:

```bash
python -m market_lab.paper_control_v1 enable --confirm PAPER_ONLY
```

Do not run it yet. Phase P2/P3 must be connected and production-gated first.
