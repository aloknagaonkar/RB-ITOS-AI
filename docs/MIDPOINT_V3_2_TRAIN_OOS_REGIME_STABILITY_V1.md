# Midpoint V3.2 TRAIN-vs-OOS Regime Stability V1

The chronology-correct validation confirms that the single frozen exit policy
has a genuine research tension:

- TRAIN is negative.
- pooled OOS-A/B/C/D is positive.
- all four individual OOS blocks are positive by mean/PF.

Before using OOS-H, this module asks whether TRAIN and OOS differ in observable
composition or regime characteristics.

## Diagnostics

Compare TRAIN vs pooled OOS by:

- direction;
- OI quality;
- T+1 observation state;
- outcome family;
- entry-time bucket;
- month;
- weekday.

For every dimension it reports:

1. composition share;
2. TRAIN economics;
3. pooled OOS economics.

## Important restriction

This is explanatory research only.

For example, if `STRONG` OI looks better than `SECONDARY`, this module does NOT
authorize a STRONG-only rule. Likewise, a profitable time bucket is not a new
entry filter.

Any new hypothesis must be defined separately and must respect the existing
leakage policy. OOS-H remains pristine.
