# V60 — Post-reentry second-leg excursion / giveback audit

V59 showed that the current post-CAP20 re-entry trigger often precedes meaningful
favorable movement, yet completed second legs eventually terminate negative.

V60 does not change the re-entry trigger and does not test a new exit rule.

For each frozen existing re-entry it measures:
- +10 / +20 / +30 / +50 / +75 / +100 reach
- MFE and MAE from re-entry
- time to peak MFE
- structural-terminal result
- peak-to-terminal giveback
- first close back to <= +20
- first close back to <= +10
- first close back to <= 0
- first negative close

The purpose is to determine whether the weak component is second-leg management
rather than re-entry qualification.
