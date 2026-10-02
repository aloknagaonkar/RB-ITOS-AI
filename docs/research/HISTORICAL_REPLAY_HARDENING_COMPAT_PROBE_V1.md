# Historical Replay Hardening Compatibility Probe V1

This probe is intentionally non-mutating.

It captures the exact current source/signatures needed before patching the next
hardening phase:

- Operations worker job lifecycle
- Operations API endpoints/job listing
- Historical Replay API
- Historical Replay date selector UI
- Replay Operations controls

The next patch will target:

1. Arbitrary date input independent of completed replay sessions.
2. Readiness-first gating and explicit availability semantics.
3. Active-job recovery after browser refresh.
4. Stale RUNNING-job detection when the recorded PID no longer exists.
5. Clear overwrite behavior for reruns.
6. No change to strategy logic or live execution safety.

Run:

```bash
python -m pytest \
  tests/test_historical_replay_hardening_compat_probe_v1.py -v

python -m market_lab.historical_replay_hardening_compat_probe_v1

python - <<'PY'
import json
p="data/live-observation/replay/hardening-compat-probe-v1.json"
d=json.load(open(p))
for name,v in d["modules"].items():
    print("\\n====",name,"====")
    print(v.get("module_source") or v)
for name,v in d["frontend"].items():
    print("\\n====",name,"====")
    print(v.get("text") or v)
PY
```
