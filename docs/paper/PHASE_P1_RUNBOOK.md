# Phase P1 Test / Runbook

## 1. Copy bundle into repository

Copy the bundle contents at repo root.

## 2. Run only the new tests

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_paper_production_foundation_v1.py -v
```

Expected: all tests pass.

## 3. Initialize schema in the real lab.db

This is a schema addition. It does not mutate existing observation/configuration rows.

```bash
python -m market_lab.paper_control_v1 init
```

Expected:

```json
{
  "status": "READY",
  "paper_enabled": false,
  "live_enabled": false
}
```

## 4. Verify quick status

```bash
python -m market_lab.paper_control_v1 status
```

Paper must remain disabled.

## 5. Start standalone service manually for validation

```bash
python -m market_lab.paper_service_v1
```

Leave it running for 5-10 seconds in a test shell, then in another shell:

```bash
python -m market_lab.paper_control_v1 status
```

The health state should show `disabled` with a recent heartbeat.

Stop with Ctrl+C.

## 6. Do NOT enable paper yet

Do not run:

```bash
python -m market_lab.paper_control_v1 enable --confirm PAPER_ONLY
```

until Phase P2 live feature input and P3 exact-ATM paper execution are wired and validated.

## Next phase

Inspect and integrate:
- production 5m OI/PCR checkpoint builder
- session imbalance baseline at 09:20
- completed NIFTY futures 5m candles
- cumulative futures VWAP
- expiry validity guard
- causal P1 -> VWAP -> P2 evaluator
