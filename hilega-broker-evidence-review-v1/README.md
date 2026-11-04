# Combined broker timestamp / finance evidence review

After-hours, offline review of existing Nov 2 captures. Verifies package pins, installed sealed release, current warmup successor status, owned private input permissions and the two local account-bound capture signatures plus their linkage. Reads ONLY the capture-verification account pin key; no broker access token, issuer root or execution authority is loaded. Does not invoke the worker identity/token helper. No broker requests.

Recomputes cross-endpoint fill comparisons from signed raw captures and aggregate finance arithmetic using the already pinned finance reviewer. Keeps missing/null fee components unknown. It does not independently authenticate broker truth, confirm report finality, certify historical timezone, allocate aggregate charges to fills, mark user-reported manual trades as strategy-owned or certify net P&L.

Outputs only a new private audit: RESULT.json, BROKER-QUESTIONS.md (draft, not sent), EVIDENCE-REQUEST.json and MILESTONES.md. It does not change the signed originals, current deployment plan, app/database/services/registry or production gate. The local pin must match the capture signing account; key rotation or scope mismatch blocks review. Support identifiers can be supplied privately to the broker, not pasted publicly with keys or tokens.

External evidence required: broker timestamp reply/case reference, final contract note or itemized report with exact fill/contract metadata, fee components and a documented rounding/attribution method. The document request is a checklist, not an automatic approval or importer.

The open-session WebSocket task remains pending under the v4 reminder. This review advances evidence organization and isolates external blockers; it is not live readiness or a substitute for a real preparation/enrollment lifecycle.

Static syntax/ZIP checks performed locally; no behavioral tests run locally. Existing signed captures are inspected on the VM.
