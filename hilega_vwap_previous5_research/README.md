# Five-session VWAP research coverage

The earlier live-audit collector found records only for 12 October and used
research-1.0.0. It cannot infer absent sessions. This separate runner reads saved
replays for 6,7,8,9,12 October and rejects strategy-version mismatches explicitly.
It does not regenerate replays, modify live audit, activate filters or restart
collectors/services. Only existing Upstox GET methods are used.

From repository root on the VM:

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_vwap_previous5_research/run.py \
  --replay-root data/research/hilega-last10-atm5-20261013-gross/replays \
  --expected-version five-minute-setup-1.2.0-pending-switch
```

Upload `data/research/hilega-vwap-previous5-replay/report.json`. The console and
report include requested-date coverage; missing/version-mismatched replays cannot
be reported as five-day success. No local tests or project execution were run.

Dependency: previously installed `hilega_vwap_signal_review/collect.py` supplies
the completed-candle VWAP calculation. Existing dotenv/httpx/project gateway
dependencies come from the VM environment. Futures active catalog is only used
for current-month sessions; older sessions require historical contract manifests.

Results label the source as reconstructed strategy replay, not original live
trades. The report classifies saved entries with VWAP context; it does not model
how rejecting a trade would change later strategy state or signals.
