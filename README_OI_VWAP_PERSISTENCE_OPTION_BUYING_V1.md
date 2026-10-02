# Strategy #2 — OI + VWAP Persistence Option Buying V1

This bundle freezes the initial paper-strategy core requested in the research discussion.

## Files

- `backend/market_lab/oi_vwap_persistence_option_buying_v1.py`
- `backend/market_lab/oi_vwap_persistence_paper_risk_v1.py`
- `tests/test_oi_vwap_persistence_option_buying_v1.py`
- `docs/strategies/OI_VWAP_PERSISTENCE_OPTION_BUYING_V1.md`
- `docs/strategies/OI_VWAP_PERSISTENCE_PAPER_INTEGRATION_V1.md`

## Install

Copy the bundle contents into the repository root.

## Test

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_oi_vwap_persistence_option_buying_v1.py -v
```

## Important

This bundle intentionally does NOT guess the repo's existing paper-executor API.
It implements the causal strategy/state machine and paper-risk state first.

After this passes, inspect the repository's actual paper execution interfaces and wire
the emitted signals into those interfaces as a separate integration commit.

Paper requires manual enable. Live remains disabled.
