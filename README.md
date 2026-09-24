# Hilega lifecycle consistency UI patch

Fixes impossible display sequences such as BULLISH_EXIT or BULLISH_CONTINUATION without a preceding active BULLISH_ENTRY.

Rules:
- BULLISH_ENTRY opens the display lifecycle.
- Every following completed candle is BULLISH_CONTINUATION until a valid exit.
- BULLISH_EXIT requires an active entry, unless the audit explicitly links to an entry outside the loaded window.
- Orphan exit/continuation events are shown as REVIEW_REQUIRED; raw audit evidence remains expandable.
- Duplicate entry while active is REVIEW_REQUIRED.
- No strategy, backend, market data, or execution logic is changed.
