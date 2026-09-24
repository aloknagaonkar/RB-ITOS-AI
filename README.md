# Hilega linked CE lifecycle patch

Fixes the case where a bullish strategy entry is recorded at one checkpoint
but its ATM±2 option candidate/lifecycle evidence is attached to a later
checkpoint.

What changes:
- Audit expansion groups all rows from the same bullish lifecycle.
- When opened, historical/live detail loading fetches the linked checkpoints
  for that lifecycle, not only the clicked candle.
- Candidate set, market snapshot, lifecycle start, updates and exit are merged
  into one read-only evidence view.
- ENTRY still shows only entry data.
- CONTINUATION remains checkpoint-progressive.
- EXIT alone may show realized exit/P&L.
- No future terminal CE result is leaked into entry/continuation rows.
- Missing exact exit remains PENDING EXACT EXIT.

This is frontend/test only.

Install:

```bash
unzip hilega-ce-linked-lifecycle-ui-patch.zip -d /tmp/
cd ~/RB-ITOS-AI
source .venv/bin/activate

python /tmp/hilega-ce-linked-lifecycle-patch/install.py --repo "$PWD" --check
```

If CHECK PASS:

```bash
python /tmp/hilega-ce-linked-lifecycle-patch/install.py --repo "$PWD" --apply
node tests/test_hilega_decision_table_v1.cjs
cd frontend
npm run build
```

Then hard-refresh the browser.
