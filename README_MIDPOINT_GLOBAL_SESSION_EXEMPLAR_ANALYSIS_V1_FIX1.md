# MIDPOINT_GLOBAL_SESSION_EXEMPLAR_ANALYSIS_V1 FIX1

Fixes canonical structural reconstruction schema.

`MIDPOINT_V2_STRUCTURAL_RECONSTRUCTION_V1` stores the 184 structural records in
top-level `rows`, not `events`.

FIX1:
- reads `rows` first, `events` only as compatibility fallback
- hard-checks loaded population against `structural_event_count`
- reads nested `v2_result.final_state` / `v2_result.entry_arm`
- preserves original structural direction for the global universe
- adds two regression tests
