# P2C_CAUSAL_RUNTIME_STATE_MACHINE_V1

Files:
- backend/market_lab/oi_vwap_causal_runtime_v1.py
- backend/market_lab/oi_vwap_causal_service_v1.py
- tests/test_p2c_causal_runtime_state_machine_v1.py
- docs/paper/PHASE_P2C_CAUSAL_RUNTIME_STATE_MACHINE_V1.md

Test:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_p2c_causal_runtime_state_machine_v1.py -v
```

Keep paper disabled:

```bash
python -m market_lab.paper_control_v1 disable
```

Manual runtime smoke test:

```bash
python -m market_lab.oi_vwap_causal_service_v1
```

In another shell:

```bash
python -m market_lab.paper_control_v1 status
python -m market_lab.paper_control_v1 detail --limit 50
```

Stop with Ctrl+C after validation.
