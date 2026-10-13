Read cached updated V2 artifacts; no replay or live changes.
python hilega_wma21_sideways_research/analyze.py --self-test
python hilega_wma21_sideways_research/analyze.py --inspect-date 2026-10-12

Requires completed hilega_ema10_trend_research exports and baseline-sessions. Uses WMA21 OF RSI9 (not price EMA10). Candidates: all window WMA values in [45,55], 3/5 consecutive completed five-minute candles; WMA range <=.5/1/2 RSI units; absolute net change <=.25/.5/1 RSI units; RSI/WMA crossings >=0/1/2. Windows reset each session; nonadjacent/missing data unavailable and kept rather than classified sideways. Features include only candles available at entry.

One/three-month and earlier-two-month summaries reconcile baseline trades/net before ranking. Thresholds diagnostic only. Entry selection retains original exits and is not a full filtered ownership/reentry replay. Later month was previously examined, not pristine unseen evidence. Output candles.csv, summary.csv, blocked-trades.csv, coverage.csv and report.json.
