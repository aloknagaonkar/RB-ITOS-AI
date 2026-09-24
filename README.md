# Active owner display priority v9

UI semantic correction.

While a trade owner is active, the visible row remains that owner's
continuation. Opposite-side ARMED evidence stays preserved internally but is not
shown as an opposite candidate until the active trade exits.

Expected replay:
09:20 BEARISH_CANDIDATE / ARMED
09:25 BULLISH_ENTRY
09:30..10:15 BULLISH_CONTINUATION
10:20 BULLISH_EXIT
10:25 BEARISH_CANDIDATE / ARMED
10:30 BEARISH_ENTRY
