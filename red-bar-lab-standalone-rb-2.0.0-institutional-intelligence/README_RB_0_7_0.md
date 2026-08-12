# RB-0.7.0 Intelligence Foundation

First Intelligence release.

It does not yet generate AI confidence or recommendations. It creates a
historical training dataset while enforcing a strict no-look-ahead boundary.

Prediction features use only information known at entry:
signal type/sequence, direction, weekday/time, entry and reference values,
setup and confirmation candles, confirmation delay, and setup risk.

Realized fields are labels only:
10-model outcomes, success rate, signal quality, best/worst exit, MFE/MAE,
completion time, and EOD benchmark outcome.

The Live page includes a date-range dataset builder. Generated CSV files are
stored below `artifacts/red_bar/intelligence/`.

Next: RB-0.7.1 Explainable Historical Confidence.
