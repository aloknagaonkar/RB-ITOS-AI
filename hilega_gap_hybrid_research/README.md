# Selective earlier-entry development comparison

Run from RB-ITOS-AI root. Python standard library only; no installer, service restart or broker access.

```bash
python hilega_gap_hybrid_research/test_hybrid_policies.py --self-test &&
python hilega_gap_hybrid_research/test_hybrid_policies.py
```

Input: data/historical-evidence/hilega-adjacent-gap-reconciled-490-v1/report.json
Output: data/historical-evidence/hilega-gap-hybrid-development-v1/{report.json,summary.csv,daily.csv,trades.csv}
Existing output is never overwritten. Use --output-root for another run.

All earlier entries retain canonical signal, confirmation window, directional WMA >=0.75, positive directional gap and expansion versus the actual previous minute. Additional exploratory gates:

- HYBRID_GAP_5_10: 5 <= directional gap < 10.
- HYBRID_EXPANSION_025_050: 0.25 <= gap expansion < 0.50.
- HYBRID_ALIGNMENT: bullish RSI9 > EMA3 > WMA21; bearish RSI9 < EMA3 < WMA21.
- HYBRID_COMBINED: all three gates above.

If the first eligible adjacent-gap observation fails a gate, retain the existing waiting control. This experiment does not recheck the early gate on later minutes. If the waiting control has already entered, retain its earlier entry. EARLIER_UNFILTERED is included as comparison, without waiting fallback.

Summary tables separate bullish/bearish, three 160-session development blocks and the already observed final ten sessions. These ten sessions are not independent validation. Thresholds are informed by previous descriptive results; no automated best-policy selection or deployment approval. A wide gap is not assumed safe.

Per-trade CSV includes signal time, selected entry/exit times and prices, path, points, gap and expansion, and difference against waiting. Denied entries are excluded from winner/loser and ratio metrics. Drawdown is measured in completed-trade order, not intratrade mark-to-market. Denied +20 counts describe canonical favorable excursions, not candidate retained gains. Fees, option fills and position interactions are excluded. Original exits are unchanged.

This uses reconciled historical indicators to reproduce frozen research. It does not repair live indicator warmup. Local validation used the available 6/7 October sample (23 signals), not the complete 490-session dataset. Run the full command on the VM to obtain the complete results.
