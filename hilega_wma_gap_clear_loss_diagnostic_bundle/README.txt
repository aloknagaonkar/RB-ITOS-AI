Hilega WMA-gap clear loss diagnostic
====================================

Purpose
-------
Explain why trades still lose after the existing ordered sequence passes:

1. unchanged canonical Hilega bullish/bearish signal;
2. directional WMA21 change >= 0.75;
3. a later consecutive one-minute close keeps WMA >= 0.75;
4. the directional EMA3-WMA21 gap is positive and expands;
5. entry is valued at that confirmation close and the canonical exit is kept.

This diagnostic does not invent or optimize another rule.  It records the
entry values, T+1/T+3/T+5 values, first post-entry warning, accepted losses,
accepted winners, denied trades and same-candle sequencing conflicts.

Install
-------

  python hilega_wma_gap_clear_loss_diagnostic_bundle/install.py

Run
---

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_gap_clear_losses.py

Important outputs
-----------------

  data/historical-evidence/hilega-wma-gap-clear-loss-diagnostics-490-v1/

  clear-trade-view.csv
      Every canonical signal and its candidate decision.

  accepted-losses-clear.csv
      Every accepted losing trade with exact entry, T+1, T+3 and T+5 values.

  accepted-winners-clear.csv
      The same columns for accepted winners, allowing direct comparison.

  parameter-comparison.csv
      Winner-versus-loser distributions, split by bullish/bearish direction.

  same-candle-audit.csv
      Exact-minute and same-five-minute-candle overlaps involving exits.

  first-warning-summary.csv
      Which component weakened first after a valid entry.

Interpretation
--------------

An accepted loss proves that WMA and gap confirmation helped select the entry
but did not guarantee continuation.  T+1/T+3/T+5 evidence is diagnostic only;
this run does not turn any checkpoint into an exit or rejection rule.

Canonical exit timestamps are five-minute candle labels.  The report also
calculates the actual completed exit close as label +4 minutes.  It separately
reports:

* entry exactly on an exit close;
* entry inside the same five-minute exit candle;
* a canonical signal sharing another trade's exit label.

Safety
------

Research only.  No live strategy, service, audit, order, paper order, quantity
or environment gate is changed.
