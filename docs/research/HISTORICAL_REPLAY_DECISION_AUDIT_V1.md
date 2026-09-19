# Historical Replay Decision Audit V1

Adds an explainable, read-only decision matrix to every expanded replay checkpoint.

Checks:
- DATA_HEALTH — required
- C1_ALL3 — required
- NEW_CANDIDATE — required
- C2_TIMING — required
- C2_PERSISTENCE — required
- FUTURES_DATA — required
- FUTURES_ALIGNMENT — required
- SPOT_CLASS — context only
- OPTION_RESOLUTION — required
- ENTRY_OPEN — required

Every row shows role, result, expected condition, actual evidence and explanation.
Final summary is one of TRADE TAKEN, TRADE NOT TAKEN, CANDIDATE IN PROGRESS, or NO TRADE CANDIDATE.

This patch does not modify the strategy or immutable audit/event files. It is only an explanation projection over already-recorded evidence.
