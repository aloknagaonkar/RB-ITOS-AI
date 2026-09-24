# Hilega current-checkpoint classifier fix

Fixes Historical Replay / Hilega Shadow table classification when a canonical entry audit includes the *later linked exit transition* so the expanded audit can show the full CE lifecycle.

The table now classifies a row only from strategy transitions whose `event_time` equals that row's checkpoint. This preserves the full linked audit while correctly rendering sequences such as:

- 09:40 `BULLISH_ENTRY` / Route A
- 09:45 `BULLISH_EXIT`
- 09:55 `BULLISH_ENTRY` / Route A
- 10:00 `BULLISH_CONTINUATION`
- 10:05 `BULLISH_EXIT`

No strategy or backend logic is changed.

## Apply

```bash
python install.py --repo ~/RB-ITOS-AI --check
python install.py --repo ~/RB-ITOS-AI --apply
node tests/test_hilega_decision_table_v1.cjs
cd frontend && npm run build
```
