# P2C.2 Full Runtime Hotfix

The live output proved that P2C.1 was only partially applied:

- authoritative `paper_enabled=false` is now correct
- but runtime still emits generic `OI_FEATURE_FAILED`
- repeated failures still appear inside one 5-minute window, indicating either the old service
  is still running or multiple causal service processes exist

This bundle is a full replacement for both runtime and service files.

## New protections

- `SESSION_BASELINE_UNAVAILABLE` is a first-class reason
- singleton service lock: `data/oi-vwap-causal-runtime.lock`
- only one evaluation per 5-minute checkpoint per running process
- P2 must be the exact next checkpoint
- paper health is always overwritten from authoritative `paper_control`
- live execution remains false

## Production action

Stop every old causal runtime before starting this one:

```bash
pkill -f "market_lab.oi_vwap_causal_service_v1" || true
sleep 2
ps -ef | grep "oi_vwap_causal_service_v1" | grep -v grep
```

The final command should print nothing.

Then start one process only.
