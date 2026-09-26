# Opening Red + VWAP Frozen Candidate OOS-H Validation v1

This is the first clean follow-up after the 100-session development study.

It does **not** search for a new VWAP threshold.

It evaluates exactly the three candidates selected before looking at OOS_H:

```text
Candidate A
recent_down_cross_or_rejection_5m

Candidate B
moving_farther_below_vwap_5m

Candidate C
A AND B
```

## Frozen definitions

Candidate A:

```text
At the red boundary/midpoint event:
price is >5 futures points below VWAP

AND

at least one futures observation during the prior 5 minutes
was within 5 points of VWAP or above VWAP.
```

Candidate B:

```text
At the event:
price is below VWAP

AND

price - VWAP is more negative than it was 5 minutes earlier.
```

Candidate C is simply A AND B.

No thresholds are changed after seeing OOS_H.

## Sources

Red structural events:

```text
data/historical-evidence/
opening-candle-midpoint-framework-v1-1-oos-h.json
```

VWAP:

```text
data/historical-evidence/
midpoint-v2-nifty-futures-vwap-v1-all180.csv
```

## Run

Copy:

```text
opening_red_vwap_oos_h_validation.py
```

to:

```text
~/RB-ITOS-AI/scripts/
```

Then:

```bash
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/opening_red_vwap_oos_h_validation.py \
  | tee /tmp/opening-red-vwap-oos-h.txt
```

## Important

This OOS-H block has been used previously in other midpoint research, but these specific red+VWAP candidate definitions were selected from the earlier 100-session red/VWAP study before this OOS-H validation. Therefore this run is useful as a fresh test of these exact candidate definitions, while still not being a permanently pristine future/live holdout.

No strategy execution or Hilega rule is changed.
