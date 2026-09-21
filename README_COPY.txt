CONTROL FAILURE INTRABAR ATTRIBUTION V6.5
==========================================

Purpose
-------
Drill inside selected V6.4 critical 5-minute signal candles at exact
1-minute resolution.

No changes to:
- V5 control-failure theory
- V6.2 expiry-aware wings
- exact-strike behavior
- strategy/execution logic

Default research targets
------------------------
Strong examples:
2026-05-18 BULLISH signal 10:00
2026-06-24 BULLISH signal 09:55
2026-06-29 BEARISH signal 10:35
2026-07-07 BEARISH signal 12:05

Weaker comparison:
2026-05-25 BULLISH signal 09:45

Method
------
For each critical 5m candle:
- freeze the ATM and expiry-aware physical strike basket used by V6.4
- inspect minute checkpoints 1..5 inside that candle
- compare exact same physical strikes at T vs T-1m
- compute:
  spot Δ1m
  CE ΔOI / PE ΔOI
  1m imbalance
  1m imbalance velocity
  1m imbalance acceleration
  strike breadth
  ATM state
  direction-specific failed response
  direction-specific pressure decay
- also report cumulative spot/OI change from the 5m candle start

No nearest strike.
No interpolation.
Missing exact minute/strike fails clearly.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_intrabar_v6_5.py -v

Run default 5 events
--------------------
python scripts/validate_control_failure_intrabar_v6_5.py

Optional: analyze all 12 V6.4 matched ±15m events
------------------------------------------------
python scripts/validate_control_failure_intrabar_v6_5.py --all-matched

Outputs
-------
data/historical-evidence/control-failure-intrabar-v6-5/
  intrabar-minute-detail-v6-5.csv
  intrabar-event-summary-v6-5.csv
  intrabar-summary-v6-5.json

Main question
-------------
Does the underlying 1-minute FAILURE or DECAY appear materially earlier
than the 5-minute V5 confirmation?
