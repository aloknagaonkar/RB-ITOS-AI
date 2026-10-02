# Midpoint V3.2 Exit Management Research V1

The false-positive diagnostic showed that the six structural false positives are
not cleanly separable at T+3:

- several have 100% acceptance;
- several have four consecutive closes;
- five of six have STRONG OI;
- one OOS false positive has very strong momentum/progress/velocity.

Therefore this phase does not add an entry filter. It keeps V3.2 frozen and
researches loss containment / profit retention after exact entry.

## Candidate policies

Small a-priori family:

```text
TIME_15
SL10_TIME15
SL5_TIME15
SL10_BE5_TRAIL5_AFTER10_TIME15
SL10_TRAIL5_AFTER5_TIME15
SL5_BE5_TRAIL3_AFTER10_TIME15
```

## Anti-lookahead semantics

A trailing or breakeven stop calculated from a completed 1-minute bar becomes
active only on the NEXT bar.

Gap-through stop:
- if next bar opens below active stop, exit at open.

Ordinary touch:
- if bar low reaches active stop, exit at stop.

Time exit:
- close of the 15th replay bar.

## Selection discipline

TRAIN alone nominates a candidate exit policy.

OOS-A/B/C/D are then displayed unchanged as validation.

No E/F/G/H. H remains untouched.
