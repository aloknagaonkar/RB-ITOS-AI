# OI Transition Minimum Evidence V1

Adds the missing quantity context to the trend-day transition research.

Short-term transition:
- Moving ATM ±2
- same physical five strikes at T and T-5

Session-to-date context:
- Fixed 09:20 ATM ±2
- same five physical strikes followed all day

Outputs:
- current CE/PE total OI
- 5m CE/PE OI delta and %
- 5m activity and imbalance
- 09:20 CE/PE OI
- CE/PE OI added today and %
- session activity and imbalance
- PCR at 09:20, PCR now, PCR change today
- 1/2/3/4 checkpoint persistence evidence

No minimum threshold is selected yet.

## Test
```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_oi_transition_minimum_evidence_v1.py -v
```

## Run
```bash
python -m market_lab.oi_transition_minimum_evidence_v1   --bullish-dates data/historical-evidence/bullish-trend-days-90d-v1.txt   --bearish-dates data/historical-evidence/bearish-trend-days-90d-v1.txt   --move-replay data/historical-evidence/trend-day-move-start-oi-replay-v1.json   --positioning 'TRAIN|data/historical-evidence/positioning-train.csv'   --positioning 'OOS_A|data/historical-evidence/positioning-oos-a.csv'   --positioning 'OOS_B|data/historical-evidence/positioning-oos-b.csv'   --positioning 'OOS_C|data/historical-evidence/positioning-oos-c.csv'   --positioning 'OOS_D|data/historical-evidence/positioning-oos-d.csv'   --output data/historical-evidence/oi-transition-minimum-evidence-v1.json   --csv-output data/historical-evidence/oi-transition-minimum-evidence-v1.csv
```

## Report
```bash
python -m market_lab.oi_transition_minimum_evidence_report_v1   --input data/historical-evidence/oi-transition-minimum-evidence-v1.json
```
