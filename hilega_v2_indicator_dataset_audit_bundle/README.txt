HILEGA V2 INDICATOR DATASET AUDIT
=================================

Purpose
-------
Audits the existing cached Hilega historical dataset before RSI/EMA/WMA
probability optimization. It creates timestamp-valid features and price-only
trend/reversal outcome labels. It does not change Hilega V1 or enable a V2 rule.

Installed folder structure
--------------------------
scripts/
  audit_hilega_indicator_dataset_v2.py
tests/
  test_audit_hilega_indicator_dataset_v2.py

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_v2_indicator_dataset_audit_bundle/install.py

Run the default audit
---------------------
PYTHONPATH=backend:. python \
  scripts/audit_hilega_indicator_dataset_v2.py

Default input
-------------
data/historical-evidence/hilega-milega-underlying-cache-v1/*.json

Default output
--------------
data/historical-evidence/hilega-indicator-dataset-audit-v2/
  report.json
  indicator-feature-matrix.csv
  data-issues.csv
  source-file-diagnostics.csv

Predeclared audit mathematics
-----------------------------
- RSI(9), EMA(3) of RSI, WMA(21) of RSI: canonical Hilega streaming engine.
- EMA/WMA difference: EMA(3) - WMA(21).
- Slope: ordinary least-squares slope over 3 completed five-minute bars.
- SLOPING_UP: slope > +0.10 indicator units per bar.
- SLOPING_DOWN: slope < -0.10 indicator units per bar.
- FLAT: absolute slope <= 0.10.
- Labels: price-only prior/forward 30-minute movement compared with 0.50 ATR(14).
- Chronological split: first 70% sessions IS, last 30% OOS.

The 0.10 flat definition is an audit baseline, not an optimized trading
threshold. Full probability research must compare continuous slope values and
lock any threshold using IS only before one-time OOS validation.

Optional sensitivity audit
--------------------------
Use a separate output directory so evidence is not overwritten:

PYTHONPATH=backend:. python \
  scripts/audit_hilega_indicator_dataset_v2.py \
  --slope-window 5 \
  --flat-epsilon 0.10 \
  --label-horizon 6 \
  --atr-multiple 0.50 \
  --output-root \
  data/historical-evidence/hilega-indicator-dataset-audit-v2-window5

Interpretation guard
--------------------
- Do not forward-fill OHLC or indicator gaps.
- Leading indicator warmup is expected and excluded.
- Any indicator gap after readiness is corruption.
- Outcome labels never use RSI, EMA or WMA.
- Do not enable WMA-rising/falling in live shadow from this audit alone.
- No broker calls, service restart, order, paper order or quantity changes.

