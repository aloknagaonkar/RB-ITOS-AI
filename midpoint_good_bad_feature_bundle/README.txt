MIDPOINT GOOD-vs-BAD CAUSAL FEATURE STUDY — 490 SESSIONS
=======================================================

Copy this entire folder into the RB-ITOS-AI repository root.

Folder structure:

  RB-ITOS-AI/
    midpoint_good_bad_feature_bundle/
      install.py
      README.txt
      files/
        scripts/research_midpoint_good_bad_features.py
        tests/test_research_midpoint_good_bad_features.py

Install:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_good_bad_feature_bundle/install.py

Run:

  PYTHONPATH=backend:. python \
    scripts/research_midpoint_good_bad_features.py

Fixed session universe:

  * 480 frozen sessions;
  * latest 10 forward sessions: 2026-09-16 through 2026-09-29;
  * exactly 490 trade-analysis sessions.

The four earlier forward sessions remain context-only for lagged ATR and HTF
levels. Their trades do not enter the analysis.

Outputs:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
    midpoint-good-bad-feature-study-490-v1/
      report.json
      all-trade-features.csv
      morning-be-features.csv
      pm-be-features.csv
      b-features.csv
      e-features.csv
      pm-b-features.csv
      pm-e-features.csv
      is-feature-statistics.csv
      oos-feature-statistics.csv
      forward-feature-statistics.csv
      family-direction-statistics.csv
      matched-good-bad-pairs.csv
      missing-data-report.csv

Safety: research only. No live configuration, service, audit, order, paper
order or quantity is modified. No automatic threshold or live rule is created.
