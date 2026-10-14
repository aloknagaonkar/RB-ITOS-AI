Hilega post-proof dynamic MFE exit validation
==============================================

This research keeps the accepted Hilega WMA-gap entry sequence unchanged and
tests dynamic profit protection only after a trade reaches +20 NIFTY points.

Control
-------

The control is the unchanged canonical exit:

* bullish: completed 5m RSI9 cross below WMA21;
* bearish: completed 5m RSI9 cross above WMA21;
* otherwise the existing session cutoff.

Candidate policies
------------------

Three giveback percentages are tested: 25%, 35% and 45% of running MFE.

ONE_MINUTE_DIRECT
    Track completed 1m closes after +20 proof and exit on the first close at
    or below the dynamic MFE floor.

ONE_MINUTE_ARM_FIVE_MINUTE_CONFIRM
    A completed 1m close arms a giveback breach.  Exit only if the condition
    still holds on a completed 5m close; otherwise clear the arm.

FIVE_MINUTE_DIRECT
    Establish proof, track MFE and evaluate the floor only with completed 5m
    closes.

For example, with MFE +100, a 35% giveback policy has a +65 floor.  The floor
moves upward when MFE increases; it never moves downward.

Install and run
---------------

  python hilega_post_proof_mfe_exit_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/research_hilega_post_proof_mfe_exits.py

Output
------

  data/historical-evidence/hilega-post-proof-mfe-exits-490-v1/

  report.json
  headline.csv
  policy-trades.csv
  candidate-exits.csv
  selected-date-examples.csv

Safety
------

Research only.  No live strategy, entry, exit, service, audit, order, paper
order, quantity or environment gate is changed.
