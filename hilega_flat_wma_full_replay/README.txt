Isolated full V2 lifecycle replay; no live changes.
PYTHONPATH=backend:. .venv/bin/python hilega_flat_wma_full_replay/run.py --self-test
PYTHONPATH=backend:. .venv/bin/python hilega_flat_wma_full_replay/run.py --end-date 2026-10-12

Four variants: BASELINE, BULLISH_FILTER, BEARISH_FILTER, COMBINED. Bullish entry veto: range of latest3 completed WMA21(RSI9) values <=0.5 AND abs(net change)<=0.5. Bearish veto: latest5 range<=2 AND abs(net change)<=0.5. No 45-55, RSI crossing, or EMA10 requirement. Insufficient history keeps entry and is not classified sideways.

Entry filter applied only when original minute confirmation would enter. Rejected confirmation cancels that pending signal, does not open actual position, and subsequent setup episodes/reentries follow original V2 policy. All setups, indicators, dual exits, cutoff, ownership and future signals rerun. Canonical setup engine remains independent of actual-position gate as in installed V2.

Historical indicator warmup carried forward once. Each variant receives equivalent prior-session seed plus the last real warmup session; baseline parity is tested. No source changes: temporary engine bindings exist only inside this standalone offline process and are restored. Separate cached research artifacts are versioned by input/engine/research signatures. Daily progress printed.

Outputs summary.csv, daily.csv, trades.csv, rejected-confirmations.csv, coverage.csv, report.json and per-date cached sessions. Inspect failures/coverage; missing/empty dates are not verified holidays. Nifty points before costs, not option P&L; selected thresholds used previously inspected data and are not independent validation. No restart, activation, service or broker calls.
