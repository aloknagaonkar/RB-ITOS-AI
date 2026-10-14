# VWAP observation in HILEGA audit inspection

Adds a read-only VWAP card to the existing shared decision audit and legacy
detailed audit views. Existing strategy decisions, gate results, immutable audit
hashes, Sandbox orders and cutoff rules are untouched. No trading workers restart.

The card displays each exact checkpoint's SETUP/CONFIRMED_ENTRY observation:
direction, futures price, futures session VWAP, ABOVE/BELOW/AT, distance,
AGREES/OPPOSES/NEUTRAL, contract identity, candle availability and age. Raw
evidence is expandable. These are diagnostics, not PASS/FAIL trading gates.

It reads the independent collector's files:

- `data/live-observation/hilega-vwap-signal-v1/signal-vwap-observations.jsonl`
- `data/research/hilega-vwap-oct13-14/report.json`

Journal rows are preferred; the research report is a fallback. Only exact signal
times are matched; no nearest future timestamp or made-up VWAP is substituted.
The card explains the five-minute typical-price proxy and historical provenance.
It does not make broker/API calls. Each request reads at most the last 4 MiB of
the journal and a research report limited to 16 MiB. The separate collector must
keep running to record future setups/entries; this patch does not start it.

From the repository root on the VM:

```bash
python hilega_vwap_audit_update/install.py --check
PYTHONPATH=backend:. .venv/bin/python -m pytest -q hilega_vwap_audit_update/tests
python hilega_vwap_audit_update/install.py
npm --prefix frontend run build
bash scripts/restart_api_only.sh
```

This package supports API baselines both before and after the strike-observation
UI patch. Installer source hashes guard other edits and create backups. If it
reports SOURCE_HASH_MISMATCH, do not bypass it; provide the changed file for an
updated compatible patch. No local tests or build have been run.

Open Audit inspection / View audit for an existing setup or confirmed entry.
For example 14 October 13:48 should show BELOW / OPPOSES / about -68.23 points
from the collected report. Exact values come from files on your VM.

For forward collection in a separate process:

```bash
PYTHONPATH=backend:. .venv/bin/python hilega_vwap_signal_review/collect.py \
  --watch --output data/live-observation/hilega-vwap-signal-v1
```

Missing records appear as Not recorded, not a failed entry. The observation is
separate from immutable strategy audit; frontend reloads it when audit details
are opened, rather than continuously polling within an already-open card.
