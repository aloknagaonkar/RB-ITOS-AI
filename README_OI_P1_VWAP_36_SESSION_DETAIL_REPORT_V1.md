# 36-session detailed report

This does **not** regenerate the study. It reads the valid V3 JSON and prints
all 36 sessions individually, first all 18 bullish then all 18 bearish.

Each session includes every OI P1 event and the actual **causal futures VWAP
candle OHLC** available at that P1.

## Run all 36

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m market_lab.oi_p1_vwap_36_session_detail_report_v1 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v3.json \
  --output data/historical-evidence/oi-p1-vwap-36-session-detail-v1.txt
```

## One session for chart validation

```bash
python -m market_lab.oi_p1_vwap_36_session_detail_report_v1 \
  --input data/historical-evidence/oi-p1-vwap-36-sessions-v3.json \
  --date 2026-08-25
```
