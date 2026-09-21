CONTROL FAILURE CONTEXT DISCRIMINATION V6.8
=============================================

Purpose
-------
Compare full-day intrabar candidates that occur near a confirmed directional
move start against candidates occurring elsewhere in the session.

Population
----------
Uses the existing V6.7 candidate file from all 28 available sessions.

NEAR_MOVE
  V6.7 same-direction candidate within +/-15m of the retrospective
  confirmed move start.

NON_MOVE
  Every other V6.7 full-day candidate.

The retrospective move start is used only as the evaluation label.
It is NOT used to construct contextual features.

Critical causality rule
-----------------------
ALL V6.8 context is computed at:

  trigger_time - 1 minute

or earlier.

No trigger-minute data and no future data are used in contextual features.

Context features
----------------
Exact expiry-aware physical basket for that date.

Pre-trigger price:
  spot trend 5m / 10m / 15m

Pre-trigger OI/PCR:
  CE delta 5m / 10m / 15m
  PE delta 5m / 10m / 15m
  imbalance 5m / 10m / 15m
  current PCR
  PCR change 5m / 10m / 15m
  5m imbalance velocity
  5m imbalance acceleration

Immediate pre-trigger structure:
  1m ATM state
  1m bullish/bearish strike breadth
  1m breadth change

Other context:
  time of day
  minutes since 09:15
  expiry-aware selected wings
  existing V6.7 intrabar failure/persistence fields

Exactness
---------
No nearest timestamp.
No nearest strike.
No interpolation.
Exact physical strikes only.
Missing context is written to the errors CSV.

No threshold optimization
-------------------------
V6.8 is discovery/attribution only.
It ranks numeric features by descriptive robust separation between
NEAR_MOVE and NON_MOVE populations.

It does NOT select a live threshold or strategy rule.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_context_discrimination_v6_8.py -v

Run
---
V6.7 must already have been run.

python scripts/validate_control_failure_context_discrimination_v6_8.py

Inputs
------
data/historical-evidence/control-failure-full-day-intrabar-v6-7/
  full-day-intrabar-candidates-v6-7.csv

data/historical-evidence/control-failure-expiry-aware-v6-2/
  expiry-aware-inventory-v6-2.csv

data/historical-evidence/historical-oi-build/<date>/
  positioning.json

Outputs
-------
data/historical-evidence/control-failure-context-discrimination-v6-8/

  context-enriched-candidates-v6-8.csv
  context-numeric-comparison-v6-8.csv
  context-categorical-comparison-v6-8.csv
  context-errors-v6-8.csv
  context-discrimination-summary-v6-8.json

Main console section
--------------------
=== PRE-TRIGGER CONTEXT DISCRIMINATION: TOP DESCRIPTIVE SEPARATIONS ===

Main research question
----------------------
What pre-trigger context distinguishes the small number of control-failure
events occurring around genuine move starts from the thousands of similar
events occurring elsewhere during the trading day?
