# Hilega decision-rule + date/time + Nifty delta UI patch

Frontend-only patch based on the current-checkpoint lifecycle classifier.

Changes:
- `Time (IST)` -> `Date / Time (IST)` using short `M/D HH:mm` format.
- `Strategy decision` -> `Strategy rule / decision` and shows compact recorded rule semantics.
- Adds `Nifty Δ from entry` for BULLISH_ENTRY / BULLISH_CONTINUATION / BULLISH_EXIT rows.
- Nifty delta is **current 5m candle close minus entry signal Nifty price**. It is chart movement, not CE P&L and not account P&L.
- Preserves existing current-checkpoint transition classifier and lifecycle consistency protections.

Compact rule labels:
- Opening entry: `ENTRY · OPEN 09:15 ALIGN → 09:20 RSI>WMA → 09:25 RSI>WMA`
- Route A: `ENTRY · RSI↑EMA + RSI>50 + RSI>WMA`
- Route B: `ENTRY · ARMED + (RSI>WMA OR EMA>WMA) + RSI↑ + EMA↑`
- Continuation: `CONTINUE · BULLISH_ACTIVE`
- Structural exit: `EXIT · RSI↓WMA21`
- Session cutoff: `EXIT · 14:55 CUTOFF`

Always run `--check` before `--apply`.
