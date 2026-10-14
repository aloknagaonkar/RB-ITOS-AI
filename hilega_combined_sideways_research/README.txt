Requires hilega_wma21_sideways_research and completed EMA10 trend research exports.
python hilega_combined_sideways_research/analyze.py --self-test
python hilega_combined_sideways_research/analyze.py --inspect-date 2026-10-12

NO 45-55 restriction. WMA flatness tested with 3/5 candles, range <=.5/1/2 RSI units, net <=.25/.5/1 RSI units, crossings >=0/1. Compare WMA-only, plus EMA10 FLAT, MIXED, or both. FLAT: abs(mean3 slopes)<=1 AND range of latest3 EMA values<=3 Nifty points. MIXED: >=2 sign changes among latest6 slopes. Bands shown in inspection are context only. No future candles; missing EMA evidence stops calculation.

Read cached artifacts only; no replay/install/restart/live changes. Original trade entries/exits retained, not full filtered lifecycle replay. Prior two months rank candidates; later-month comparison is not pristine unseen validation. Export summary.csv, candles.csv, blocked-trades.csv and report.json in data/historical-evidence/hilega-combined-sideways-research-v1.
