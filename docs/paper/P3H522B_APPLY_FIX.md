# P3H.5.2.2b

Fixes packaging/integration only. The previous git patch was malformed.

Strategy semantics remain unchanged:
- moving ATM±2 recent OI stays positioning-only;
- fixed 09:20 ATM±2 uses positioning first;
- exact same timestamp/strike option-OHLC OI is fallback only when the fixed
  strike is absent from the moving positioning cache;
- no nearest strike and no interpolation.
