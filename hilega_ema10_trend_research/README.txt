Read-only EMA10 price slope / persistence entry-filter research.
PYTHONPATH=backend:. .venv/bin/python hilega_ema10_trend_research/run.py --self-test
PYTHONPATH=backend:. .venv/bin/python hilega_ema10_trend_research/run.py --end-date 2026-10-12

Uses installed V2 timing rules. Three months: 2026-07-13 to 2026-10-12; one month: 2026-09-13 to 2026-10-12. Baseline sessions are cached under research output for resumability; first calculation can take time. Progress printed for each session. Exact complete historical warmup required; incomplete sessions are identified, not replaced with zero trades. Empty/missing dates are not verified holidays.

EMA10 on Nifty 5m closes, continuous session history. Features use latest completed 5m candle available at entry. Threshold grid: 0, .5, 1, 2, 3, 5 points/bar; persistence 1/2/3 bars; optional abs(mean3) <= .5/1 flat exclusion. Strong/weak/flat thresholds are hypotheses, not established rules. Earlier two months rank candidates with >=30 retained trades; later month provides chronological comparison, not pristine unseen evidence.

IMPORTANT: This filters original V2 trades and keeps original exits/prices; it is not a full filtered-strategy replay. Blocking an entry can change later ownership/setup opportunities. Full lifecycle replay is required before promotion. Results are Nifty points before costs, not option P&L. No installer, restart, broker or order APIs. Only research files written.
