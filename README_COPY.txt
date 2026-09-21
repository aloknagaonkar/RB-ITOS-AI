CONTROL FAILURE FULL-DAY INTRABAR FALSE-POSITIVE VALIDATION V6.7
================================================================

SESSION POPULATION
------------------
Uses ALL currently available frozen historical sessions from the V6.2
expiry-aware inventory.

Expected from the current population:
- 28 AVAILABLE sessions
- 8 UNAVAILABLE sessions

The 8 unavailable dates are not silently removed. They are reported explicitly.

PURPOSE
-------
Test whether intrabar control-failure persistence still works when scanning
the ENTIRE trading day instead of only known move-start candles.

No threshold optimization is performed.

FROZEN VARIANTS
---------------
A
  >= 1 direction-control failure
  causal trigger = first failure minute

B
  >= 2 direction-control failures
  causal trigger = second failure minute

C
  >= 2 failures
  AND first failure <= minute 2
  causal trigger = second failure minute

D
  >= 2 failures
  AND direction-normalized next-2m continuation after first failure > 0
  trigger occurs only after both:
  - second failure is observable
  - both continuation minutes are observable

E
  D
  AND first failure <= minute 2

IMPORTANT
---------
Variant triggers are causal minute timestamps.
They are NOT automatically assigned to the 5-minute candle close.

SCAN METHOD
-----------
For every available session:
- scan all exact clock-aligned 5-minute windows
- use 1-minute checkpoints inside each window
- evaluate BOTH bullish and bearish control failure
- use V6.2 expiry-aware basket width for that session
- exact physical strikes only
- exact minute timestamps only
- no nearest strike
- no interpolation
- missing data is reported

FORWARD VALIDATION
------------------
Measured from each variant's causal trigger minute:

+5m
+10m
+15m
+30m

median and mean directional movement
hit rates
30m MFE
30m MAE

Also report:
- signals/session
- sessions with signals
- candidates within +/-15m of the known move start in the frozen session direction
- candidates elsewhere in the day

The known move start is evaluation-only and is never used to generate
a candidate.

TEST
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_full_day_intrabar_v6_7.py -v

RUN
---
python scripts/validate_control_failure_full_day_intrabar_v6_7.py

INPUTS
------
data/historical-evidence/control-failure-expiry-aware-v6-2/
  expiry-aware-inventory-v6-2.csv

data/historical-evidence/historical-oi-build/<date>/
  positioning.json

data/historical-evidence/
  trend-day-move-start-oi-replay-v1.json

OUTPUTS
-------
data/historical-evidence/control-failure-full-day-intrabar-v6-7/

  full-day-intrabar-candidates-v6-7.csv
  full-day-intrabar-summary-v6-7.csv
  full-day-intrabar-errors-v6-7.csv
  full-day-intrabar-summary-v6-7.json

MAIN QUESTION
-------------
Does repeated intrabar price-vs-OI control failure plus short-horizon
continuation remain useful across ALL intraday windows, or did it look
strong mainly because earlier analysis started near known move starts?
