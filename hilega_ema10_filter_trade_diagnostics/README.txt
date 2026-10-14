Analyze the existing EMA10 trend research CSV exports.
python hilega_ema10_filter_trade_diagnostics/analyze.py --self-test
python hilega_ema10_filter_trade_diagnostics/analyze.py

Targets bullish S0.5_P2_FLATNone and S2_P1_FLAT0.5; bearish S0_P1_FLATNone. Outputs entry/exit details, recorded slope evidence, avoided losers, blocked winners, kept losers and daily totals. Every candidate must reconcile to summary.csv across all three periods. Missing exported prior-candle evidence is labelled UNAVAILABLE and causes reconciliation failure rather than invented membership. Baseline is not recalculated; no restart or live changes.

Provide reconciliation.csv, avoided_loser.csv, blocked_winner.csv and kept_loser.csv for analysis. First stage only: fixed original entries/exits. Full filtered-strategy ownership/reentry replay remains necessary before deployment.
