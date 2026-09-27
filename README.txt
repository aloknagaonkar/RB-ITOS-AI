MIDPOINT + VWAP DELAYED / REBREAK RESEARCH V1.1
=================================================

WHAT CHANGED
------------
1. Study A now re-evaluates the FULL frozen Candidate A rule at T+1..T+10.
   It no longer treats "still > +5" or "still < -5" by itself as a new
   delayed Candidate A confirmation.

2. Study B now records duration fields:
   - T0 -> retest
   - retest -> temporary reclaim
   - temporary reclaim -> failed reclaim
   - retest -> failed reclaim
   - failed reclaim -> rebreak
   - retest -> rebreak
   - T0 -> rebreak

3. Coverage now explicitly reports:
   - all framework events
   - boundary-break events
   - no-boundary-break events
   - study-eligible events

INSTALL
-------
Copy:
  scripts/midpoint_vwap_delayed_and_rebreak_research.py

into:
  ~/RB-ITOS-AI/scripts/

RUN
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_delayed_and_rebreak_research.py \
  | tee /tmp/midpoint-vwap-delayed-and-rebreak-research-v1-1.txt

EXPECTED 25 AUG SANITY CHECK
----------------------------
BEARISH:
- T0 = 09:39
- Candidate A at T0 = False
- delayed full Candidate A should be around 09:42
- delay = 3m
- confirmation VWAP distance about -8.31

BULLISH:
- 09:32 must NOT be accepted merely because VWAP distance remains > +5.
- The script must re-check the complete 5-minute causal interaction.

BEARISH REBREAK:
- retest around 11:58
- failed reclaim around 11:59
- rebreak around 12:00
- failed->rebreak should be about 1 minute

SAFETY
------
Research-only.
Candidate A unchanged.
Hilega unchanged.
No runtime changes.
No orders.
No quantity.
No execution.
