# Directional badge label fix v8

The row semantics were already direction-aware, but the visible "Signal detected"
badge in HilegaDecisionTable was still hard-coded to BULLISH_ENTRY,
BULLISH_CONTINUATION and BULLISH_EXIT.

This patch makes that badge call the existing direction-aware
displayDecisionText(..., reportDirection(...)) function.

No UI redesign and no strategy/backend changes.
