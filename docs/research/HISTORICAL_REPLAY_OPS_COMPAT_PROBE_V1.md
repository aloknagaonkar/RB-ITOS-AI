# Historical Replay Operations Compatibility Probe V1

Purpose: verify the exact current interfaces before adding UI controls for:

1. date selection
2. readiness check
3. download missing historical data
4. replay run
5. run/job status

The probe is read-only. It does not:
- download data
- run replay
- change strategy logic
- modify audit files
- place orders
- enable paper/live execution

It reports:
- route paths and HTTP methods from `historical_replay_data_api_v1`
- endpoint signatures
- public callables/signatures from the data/readiness modules
- current replay runner callables/signatures
- replay-related routes registered in the FastAPI app
- `_main()` source when available, so CLI arguments can be verified

Run:

```bash
python -m pytest tests/test_historical_replay_ops_compat_probe_v1.py -v

python -m market_lab.historical_replay_ops_compat_probe_v1 \
  --output data/live-observation/replay/ops-compat-probe-v1.json \
  > /tmp/replay-ops-compat.txt

cat data/live-observation/replay/ops-compat-probe-v1.json
```
