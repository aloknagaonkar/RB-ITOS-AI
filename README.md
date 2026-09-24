# Hilega latest-first + Nifty points UI patch

Frontend-only.

What it does:
- keeps lifecycle derivation chronological (required for correct ENTRY/CONTINUE/EXIT state)
- reverses only the final rendered/filtered rows so the newest candle appears at the top
- preserves Nifty delta as `current Nifty close - original entry Nifty`
- works with the reconstructed-entry projection because its projected entry transition carries recorded `signal_spot`

No strategy rules, backend evidence, option lifecycle logic, or workers are changed.
