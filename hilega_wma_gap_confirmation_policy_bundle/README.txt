HILEGA WMA-GAP CONFIRMATION POLICY RESEARCH V1
==============================================

Purpose
-------
Compare three causal post-signal confirmation policies over the same 490 Hilega
sessions. This is research-only and does not alter the canonical signal, exit,
live strategy, services, audits, orders, paper orders or quantity.

Policies
--------
1. CURRENT_FIRST_CONFIRMATION
   Enter on the first completed one-minute close where directional WMA change
   remains >=0.75 and the positive directional EMA3/WMA21 gap expands.

2. NEXT_CLOSE_PERSISTENCE
   Require the complete confirmation predicate on two consecutive completed
   one-minute closes. Enter on the second close. A later consecutive pair may
   qualify before the T+10 observation window ends.

3. EARLY_RECONFIRMATION_T3_T5
   If the first confirmation occurs T+0 through T+2 after the five-minute signal
   becomes actionable, do not enter immediately. Require another complete
   confirmation during T+3 through T+5. If the first confirmation occurs T+3
   through T+10, use that confirmation directly.

Timing
------
A five-minute signal labelled HH:MM becomes actionable at HH:MM+5. T+0, T+1,
etc. are measured from that actionable timestamp, not from the candle label.

Install and run
---------------
  python hilega_wma_gap_confirmation_policy_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/research_hilega_wma_gap_confirmation_policies.py

Outputs
-------
data/historical-evidence/hilega-wma-gap-confirmation-policies-490-v1/report.json
data/historical-evidence/hilega-wma-gap-confirmation-policies-490-v1/headline.csv
data/historical-evidence/hilega-wma-gap-confirmation-policies-490-v1/trade-results.csv
data/historical-evidence/hilega-wma-gap-confirmation-policies-490-v1/policy-comparison.csv

Validation rules
----------------
* Bullish and bearish results are always reported separately.
* Results are reported across three chronological 160-session development blocks.
* The latest ten sessions remain labelled OBSERVED_FORWARD; they have already
  been inspected and are not a new untouched OOS cohort.
* Denied losses saved and denied winners lost are reported independently.
* +20 and top-decile moves destroyed are explicitly counted.
