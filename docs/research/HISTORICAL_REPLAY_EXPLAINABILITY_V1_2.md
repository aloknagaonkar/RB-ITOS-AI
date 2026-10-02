# Historical Replay Explainability V1.2

UI-only explainability enhancement.

Every strategy stage now shows:
1. STEP
2. RESULT
3. REASON
4. NEXT ACTION

Important presentation changes:
- raw `C2_ELIGIBILITY = DUE` is displayed as `ELIGIBLE` once the exact C1+5m checkpoint has been reached
- rejected futures alignment explains the candidate direction, observed futures state, and required supporting futures states
- rejected C2 decisions explicitly state that option resolution and entry were not attempted
- terminal observations get a summary panel showing stopped-at stage, result, candidate, futures state, required futures state, reason, and next action

This patch does not change strategy logic, replay logic, risk logic, entry/exit rules, data, or API responses.
