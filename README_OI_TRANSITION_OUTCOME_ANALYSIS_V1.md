# OI Transition Outcome Analysis V1

Compares successful vs failed OI transitions. Success = direction-adjusted +20m move > 0; failure <= 0. Future price is used only as a historical outcome label.

Also measures the first later opposite OI candidate: minutes to it, points earned/lost before it, OI activity/imbalance there, and whether that opposite candidate itself works over +20m. An opposite candidate is not automatically a trend change.

## Test
```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_oi_transition_outcome_analysis_v1.py -v
```

## Run
```bash
python -m market_lab.oi_transition_outcome_analysis_v1 \
  --input data/historical-evidence/oi-pattern-control-timing-v1.json \
  --output data/historical-evidence/oi-transition-outcome-analysis-v1.json
```

## Report
```bash
python -m market_lab.oi_transition_outcome_analysis_report_v1 \
  --input data/historical-evidence/oi-transition-outcome-analysis-v1.json
```

## Aug 25 lifecycle
```bash
python -m market_lab.oi_transition_outcome_analysis_report_v1 \
  --input data/historical-evidence/oi-transition-outcome-analysis-v1.json \
  --example-date 2026-08-25
```

## Sep 8 lifecycle
```bash
python -m market_lab.oi_transition_outcome_analysis_report_v1 \
  --input data/historical-evidence/oi-transition-outcome-analysis-v1.json \
  --example-date 2026-09-08
```
