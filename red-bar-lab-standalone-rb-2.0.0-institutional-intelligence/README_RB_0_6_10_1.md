# RB-0.6.10.1 None-safe Live Evaluation Hotfix

This hotfix fixes a Live Monitor crash introduced in RB-0.6.10.

## Problem

During live trading, some actionable exit models can legitimately remain OPEN.
OPEN models store `points = None` until they close.

The RB-0.6.10 best/worst model summary attempted to calculate:

`float(row["points"])`

across both CLOSED and OPEN models. This caused:

`TypeError: float() argument must be a string or a real number, not 'NoneType'`

## Fix

Best/Worst actionable model calculations now use only models with a non-null
`points` value.

OPEN actionable models remain:
- visible;
- counted as actionable_open;
- excluded from finalized best/worst calculations until they close.

## No strategy change

This hotfix does NOT modify:
- the 10 actionable model rules;
- the EOD informational benchmark;
- entry rules;
- confirmation rules;
- stop logic;
- target logic;
- signal lifecycle semantics;
- historical or live stored data.
