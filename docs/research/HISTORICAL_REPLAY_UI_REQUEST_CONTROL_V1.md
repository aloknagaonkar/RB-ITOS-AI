# Historical Replay UI Request Control V1

Problem:
Opening Historical Replay automatically launched both:
- Replay Session Inventory scan
- Replay Operations readiness check

Both calls can be expensive. The UI had no bounded request timeout, so the page
could remain indefinitely in "Scanning..." / "Checking readiness...".

Change:
- Inventory no longer auto-scans on component mount.
- Readiness no longer auto-checks when selected date changes.
- User explicitly starts each operation.
- Replay operations requests get a 20-second browser timeout when the current
  requestJson implementation matches the known form.

This does not alter replay/readiness semantics. It only changes request timing
and UI failure behavior.
