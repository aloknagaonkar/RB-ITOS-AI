# Hilega CE progressive / no-lookahead UI patch

Purpose: fix the expanded five-CE table so an entry candle does not display the
eventual exit premium and realized P&L from the same completed trade.

Changes:
- ENTRY row: exact recorded CE entry only; exit/P&L hidden.
- BULLISH_CONTINUATION row: latest option lifecycle update available by that
  row's completion; terminal exit remains hidden.
- BULLISH_EXIT row: exact recorded terminal CE exit and realized P&L.
- If an exact exit is not recorded, status is `PENDING EXACT EXIT`; no later
  premium is substituted.
- Entry/exit summary cards use only strategy transitions at the current
  checkpoint, so a linked future exit cannot appear in an entry row.
- Each expanded historical/live row receives its own checkpoint horizon rather
  than the page-wide playback horizon.

This patch is frontend/test only. It does not alter:
- Hilega strategy rules
- historical evidence
- live-shadow worker
- market-data acquisition
- execution/paper order settings

Install:

```bash
unzip hilega-ce-progressive-no-lookahead-ui-patch.zip -d /tmp/
cd ~/RB-ITOS-AI
source .venv/bin/activate

python /tmp/hilega-ce-progressive-no-lookahead-patch/install.py   --repo "$PWD" --check
```

Only if CHECK PASS:

```bash
python /tmp/hilega-ce-progressive-no-lookahead-patch/install.py   --repo "$PWD" --apply

node tests/test_hilega_decision_table_v1.cjs

cd frontend
npm run build
```

Then hard-refresh the browser.

Expected behavior for a completed trade:
- Entry candle: entry time/premium; exit and realized P&L are `—`.
- Continuation: no terminal exit/P&L leakage.
- Exit candle: exact exit time/premium and realized P&L.
