STRIKE BREADTH TRANSITION V3
===========================

Copy into the root of ~/RB-ITOS-AI preserving folders.

Files
-----
scripts/analyze_strike_breadth_transition_v3.py
tests/test_analyze_strike_breadth_transition_v3.py

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_analyze_strike_breadth_transition_v3.py -v

Run
---
python scripts/analyze_strike_breadth_transition_v3.py   --input data/live-observation/analysis/2026-09-21-fixed-event-oi-pm2-per-strike-v2.csv

Research outputs
----------------
- bullish/bearish/mixed strike count
- bullish/bearish breadth %
- ATM state
- ATM +/-1 breadth
- ATM +/-2 breadth
- CE delta acceleration
- PE delta acceleration
- per-strike imbalance velocity
- aggregate imbalance velocity

This module is research-only and does not modify strategy or execution logic.
