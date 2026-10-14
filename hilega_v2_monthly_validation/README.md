# Tested V2: one-month and three-month validation

Policy: the installed V2 alignment/dual-exit research engine. V1 canonical setup OR completed-five-minute alignment setup; minute WMA strength >=0.75 plus persistence and positive expanding gap; completed-five-minute RSI9 AND EMA3 opposite WMA21 exit; exit-first replacement; forced cutoff 14:55. EMA10 price exit is not part of this policy.

No installation or restart is needed. Extract into RB-ITOS-AI and run:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
unzip -o hilega_v2_monthly_validation.zip
PYTHONPATH=backend:. python hilega_v2_monthly_validation/run.py --self-test &&
PYTHONPATH=backend:. python hilega_v2_monthly_validation/run.py --end-date 2026-10-09
```

The runner uses the installed replay engine and its configured historical/recovery candle roots. Optional repeated --cache-root arguments override those roots. Output defaults to data/historical-evidence/hilega-v2-monthly-validation-v1, a separate validation folder. No order API, live strategy modification or service change is made.

Windows end at Oct 9, the last completed session available when requested:
- One calendar month: September 10–October 9, 2026.
- Three calendar months: July 10–October 9, 2026.

Run uses only earlier sessions for each date's indicator warmup. It exports summary.csv, daily.csv, trades.csv, losses.csv, coverage.csv and report.json. Trades include direction, setup, signal/entry/warning/exit times, prices, points, MFE/giveback, strength, gap and expansion. Session reports are cached inside the separate output folder. Profit factor = gross gained points / gross lost points. Drawdown is calculated in completed-trade chronological order, not intratrade equity.

Included local_results:
One-month reconstructed result has 20 evaluated sessions, 104 trades (49 winners, 55 losers), gains 2050.20, losses 1231.45, net +818.75, profit factor 1.66487 and closed-trade drawdown 344.40. Ten date files have no candles; these are excluded and have not been independently checked against an exchange calendar.

Three-month local output is PARTIAL: only 34 sessions evaluated, 41 calendar dates have no cache, 16 caches are empty, and one early date lacks indicator warmup. Its aggregate is not a validated complete three-month result. Your VM's longer historical cache is required to complete this window. Review coverage.csv before treating any output as complete. Missing/empty inputs must never be interpreted as no signals.

Reconstructed Nifty results exclude option fills, fees and slippage. Chart/live indicator parity remains unconfirmed. This is retrospective research of a policy already selected using development evidence, not independent out-of-sample proof or authorization for live promotion.

Validation: calendar-window boundaries, gain/loss reconciliation, trade ordering/drawdown and empty groups passed. Last five daily totals reproduce the prior tested results: Oct 5 +133.15; Oct 6 -50.70; Oct 7 +49.90; Oct 8 -58.80; Oct 9 +206.75.
