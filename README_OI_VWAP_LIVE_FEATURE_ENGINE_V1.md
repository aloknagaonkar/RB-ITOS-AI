# OI_VWAP_LIVE_FEATURE_ENGINE_V1

Adds:
- causal 5m OI checkpoint builder
- moving ATM±2 same-strike 5m delta
- fixed 09:20 ATM±2 session buildup
- PCR 5m change
- completed-only futures VWAP calculator
- bridge helpers for Strategy #2

No live paper entry is enabled by this phase.

Test:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_oi_vwap_live_feature_engine_v1.py -v
```
