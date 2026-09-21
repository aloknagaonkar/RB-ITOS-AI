CONTROL FAILURE INTRABAR PERSISTENCE & CONTINUATION V6.6
==========================================================

Purpose
-------
Use the 12 V6.5 one-minute events to test whether genuine directional-start
candles differ from weaker/early candidates through:

- number of direction-control failures in the 5m candle
- longest consecutive failure run
- timing of the first failure
- cumulative direction-normalized price displacement at minute 1..5
- price continuation during the next 1m / 2m after first failure
- ATM transition/support after first failure
- strike-breadth transition/support after first failure
- decay count

No changes to:
- V5 control-failure theory
- V6.2 expiry-aware wings
- V6.3 ±15m evaluation logic
- V6.5 one-minute event generation
- strategy/execution logic

No threshold optimization is performed.

Outcome comparison
------------------
Events are grouped DESCRIPTIVELY using only the sign of already-measured
directional follow-through:

POSITIVE_15_AND_30
  move_15m > 0 and move_30m > 0

MIXED_15_30
  only one of move_15m / move_30m is positive

NON_POSITIVE_15_AND_30
  neither is positive

This grouping is research-only and is NOT a live trading rule.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_intrabar_persistence_v6_6.py -v

Run
---
IMPORTANT:
V6.6 expects V6.5 to have been generated with --all-matched, because it is
intended to analyze all 12 matched events.

python scripts/validate_control_failure_intrabar_v6_5.py   --all-matched

python scripts/validate_control_failure_intrabar_persistence_v6_6.py

Outputs
-------
data/historical-evidence/control-failure-intrabar-persistence-v6-6/
  intrabar-persistence-event-detail-v6-6.csv
  intrabar-persistence-group-summary-v6-6.csv
  intrabar-persistence-summary-v6-6.json

Key event metrics
-----------------
failure_count_5m
max_consecutive_failure_count
first_failure_minute_from_candle_start
decay_count_5m

directional_cum_price_m1 ... m5

next_1m_directional_after_first_failure
next_2m_directional_after_first_failure
next_1m_continues
next_2m_continues

atm_support_at_first_failure
atm_support_after_first_failure

breadth_support_at_first_failure
breadth_support_after_first_failure

Main question
-------------
Does repeated/persistent price-vs-OI control failure plus continued
directional price displacement distinguish the cleaner move-start candles
from early or weaker control-failure events?

V6.6 deliberately does NOT select a threshold from these 12 events.
