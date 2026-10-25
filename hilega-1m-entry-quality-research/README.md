# One-minute entry-quality research

Research only. No live files, services, broker calls or orders are changed.
Uses installed policy version bullish-gap2-full-wma2-2.0.0-wma40-reversal.

The unchanged 5m and 1m controls run alongside four independent 1m variants:

| Variant | Bullish entry | Bearish entry |
|---|---|---|
| RSI_EMA50 | RSI9 >50 AND EMA3 of RSI >50 | Both <50 |
| WMA50 | WMA21 of RSI >50 | WMA21 <50 |
| EMA10_SLOPE3 | Price EMA10 change >=+3 per completed 1m | Change <=-3 |
| EMA10_DISTANCE30 | 0 < close minus EMA10 <=30 | 0 < EMA10 minus close <=30 |

Each extra filter applies at an otherwise passing follow-up entry, including
the confirmed bullish reversal monitor. Existing failure/touch-wait lifecycle
handles rejection. A rejection does not unconditionally preserve the setup.
Qualification, exits, cutoff and indicator periods retain the original rules.
Thresholds are exploratory fixed hypotheses. Do not select a live rule on these
October results alone; validate separately on earlier unseen sessions.

Run from repository root with PYTHONPATH=backend:. and the same captured inputs
as the October 1m batch. Reports include full session JSON audits, summary.md,
daily-trade-comparison.md and signal-comparison.md. A dash is no execution from
that exact setup, not proof of a direct filter rejection. Full audit supplies
entry_quality reason on evaluated filter decisions.

No project tests or replays were run locally. Run test_quality.py on the VM.
