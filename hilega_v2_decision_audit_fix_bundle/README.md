# V2 decision audit correction
Preserves distinct minute decision timestamps, recorded entry/exit prices and points, and original processed events across recovery. Corrects bearish point sign. Minute decisions display their actual timestamp rather than a fictitious five-minute window. Strategy and broker execution are unchanged.

From repository root:
```
source .venv/bin/activate
python hilega_v2_decision_audit_fix_bundle/install.py && ./scripts/restart.sh && ./scripts/status.sh
```
Refresh the browser afterward. No historical evidence rebuild is required.
