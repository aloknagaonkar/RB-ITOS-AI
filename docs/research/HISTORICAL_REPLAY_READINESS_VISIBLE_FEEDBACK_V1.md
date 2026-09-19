# Historical Replay Readiness Visible Feedback V1

Problem:
When readiness data is unchanged, clicking **Check readiness** completes but the
screen looks identical. Users cannot tell whether the request ran.

Fix:
- Show `Checking readiness for YYYY-MM-DD…` while the request is active.
- After a successful response, keep a visible confirmation:
  `Readiness checked for YYYY-MM-DD at HH:MM:SS`.
- Also state whether replay prerequisites are ready or not ready.
- Clear the confirmation when the selected date changes.

No readiness logic, replay logic, data rules, or execution behavior changes.
