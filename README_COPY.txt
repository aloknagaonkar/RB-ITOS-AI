BRANCH B — TREND / PULLBACK CONTINUATION — PRICE STRUCTURE V1
==============================================================

Purpose
-------
Start Branch B independently from the paused Control-Failure branch.

The first question is deliberately simple:

Can causal PRICE STRUCTURE alone identify the continuation/pullback moves
we want to capture?

OI/PCR are NOT used in the trigger.

Population
----------
Uses all AVAILABLE sessions from the existing expiry-aware inventory
(currently expected to be 28 sessions).

Source
------
Existing historical positioning.json files are reused only as a source of the
exact minute-by-minute Nifty spot series.

No new historical data build is required.

5-minute price structure
------------------------
Exact 5-minute checkpoints are built from the minute spot series.

EMA family:
  EMA 3
  EMA 10
  EMA 21

These match the price-structure family being studied on the user's chart.

Trend definition
----------------
Bullish:
  EMA3 > EMA10 > EMA21
  EMA21 slope over prior 3 bars > 0

Bearish:
  exact mirror.

The trend must already exist BEFORE the trigger bar.

Frozen discovery variants
-------------------------

A_TREND_RESUME
  - established trend before trigger
  - at least one counter-trend 5m close in previous 3 bars
  - trigger close breaks beyond the prior 2-bar pullback structure

B_CONTROLLED_PULLBACK
  A
  +
  pullback closes do not close through EMA21

C_EMA10_RECLAIM
  B
  +
  pullback reaches/touches EMA10 zone
  +
  trigger closes back on trend side of EMA3

D_STRUCTURE_HOLD
  B
  +
  pullback close-extreme holds the earlier close structure
  (higher structural low for bullish / lower structural high for bearish)

Candidate emission
------------------
Candidates are EDGE-TRIGGERED.

If a condition remains true for multiple 5m bars, it does NOT emit a new
candidate on every bar. It emits only when the condition changes false -> true.

This avoids manufacturing repeated signals from one continuation episode.

Forward evaluation
------------------
From the causal 5m trigger close:

  +5m
  +10m
  +15m
  +30m

  30m MFE
  30m MAE

Also reported descriptively:
  whether the candidate is same-direction and within +/-15m of the existing
  retrospective trend-day move-start marker.

The move-start marker is EVALUATION ONLY and never participates in detection.

Important
---------
This is candidate discovery, NOT a finished trading rule.

No option entry.
No CE/PE selection.
No OI/PCR filter.
No profit threshold.
No parameter optimization.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_trend_pullback_continuation_price_structure_v1.py -v

Run
---
python scripts/validate_trend_pullback_continuation_price_structure_v1.py

Outputs
-------
data/historical-evidence/trend-pullback-continuation-price-v1/

  price-structure-candidates-v1.csv
  price-structure-summary-v1.csv
  price-structure-errors-v1.csv
  price-structure-summary-v1.json

Main console section
--------------------
=== BRANCH B PRICE-STRUCTURE DISCOVERY ===

What we inspect first
---------------------
For A/B/C/D, bullish and bearish separately:

- events
- sessions
- signals/session
- near-move count
- median +15m
- median +30m
- hit15
- hit30
- MFE30
- MAE30

This first pass answers whether the simple continuation structure itself
contains enough directional behavior to justify deeper research.

Only after that do we add OI/PCR as confirmation.
