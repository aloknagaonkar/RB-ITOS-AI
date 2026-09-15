# OI P1 + VWAP 36 Sessions V2

This replaces the first join that produced `NA` for CE5Δ, PE5Δ, PCRΔ, P2/P3/P4 and outcomes.

## Population

Exactly the frozen 36 confirmed trend sessions:

- 18 bullish trend days
- 18 bearish trend days

No mixed days in this run.

## Inputs

Primary rich P1 source:
`data/historical-evidence/oi-pattern-control-timing-v1.json`

Outcome enrichment:
`data/historical-evidence/oi-transition-outcome-analysis-v1.json`

VWAP:
`data/historical-evidence/vwap-trend-day-profile-v1.json`

## Causality

For P1 stamped 14:25:

- the last completed 5m VWAP candle is 14:20, available at 14:25;
- the 14:25 candle itself closes only at 14:30 and is not used as P1 information.

## Integrity gates

The script deliberately FAILS if it cannot find:

- CE 5m OI delta
- PE 5m OI delta
- PCR 5m change

This prevents another apparently successful report with silent `NA` columns.

## Run

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest tests/test_oi_p1_vwap_36_sessions_v2.py -v

python -m market_lab.oi_p1_vwap_36_sessions_v2 \
  --pattern-events data/historical-evidence/oi-pattern-control-timing-v1.json \
  --outcomes data/historical-evidence/oi-transition-outcome-analysis-v1.json \
  --vwap-profile data/historical-evidence/vwap-trend-day-profile-v1.json \
  --output data/historical-evidence/oi-p1-vwap-36-sessions-v2.json \
  --csv-output data/historical-evidence/oi-p1-vwap-36-sessions-v2.csv

python -m market_lab.oi_p1_vwap_36_sessions_report_v2 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v2.json
```

For Aug 25:

```bash
python -m market_lab.oi_p1_vwap_36_sessions_report_v2 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v2.json \
  --date 2026-08-25
```

For Sep 8:

```bash
python -m market_lab.oi_p1_vwap_36_sessions_report_v2 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v2.json \
  --date 2026-09-08
```
