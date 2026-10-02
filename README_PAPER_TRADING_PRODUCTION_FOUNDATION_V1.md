# PAPER_TRADING_PRODUCTION_FOUNDATION_V1

Files:

- `backend/market_lab/paper_production_storage_v1.py`
- `backend/market_lab/paper_service_v1.py`
- `backend/market_lab/paper_control_v1.py`
- `tests/test_paper_production_foundation_v1.py`
- `docs/paper/PRODUCTION_PAPER_FOUNDATION_V1.md`
- `docs/paper/PHASE_P1_RUNBOOK.md`

This is deliberately additive. It does not modify the existing collector, API, runtime,
frontend, or research code in Phase P1.

After the tests pass, the next bundle will connect the causal live feature pipeline and
then wire the independent service into the platform start/restart lifecycle.
