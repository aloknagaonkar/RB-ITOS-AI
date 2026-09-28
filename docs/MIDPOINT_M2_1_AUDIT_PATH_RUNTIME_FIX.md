# M2.1 audit path runtime fix

The three failures are caused by a Python default-argument binding issue, not
by the M2 live/replay behavior.

`AUDIT_PATH` was captured when `_all_rows` was defined. Existing tests patch
`ui.AUDIT_PATH`, so `_all_rows()` must resolve the module variable at call time.

No UI, replay, ownership, CAP20, V62, or execution logic changes.
