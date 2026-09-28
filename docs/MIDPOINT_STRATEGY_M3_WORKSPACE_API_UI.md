# Midpoint Strategy — M3A Workspace/API/UI Integration

## Confirmed shared application paths

This phase is based on the current Hilega integration structure:

- API registration: `backend/market_lab/api.py`
- Hilega live UI router pattern:
  `backend/market_lab/hilega_milega_live_shadow_ui_v1.py`
- Hilega frontend workspace:
  `frontend/src/hilegaMilegaShadow.tsx`
- application workspace/navigation:
  `frontend/src/App.tsx`
- shared worker:
  `backend/market_lab/live_shadow_worker_v1.py`
- Hilega coordinator:
  `backend/market_lab/hilega_milega_live_shadow_v1.py`
- directional coordinator:
  `backend/market_lab/hilega_directional_live_shadow_v1.py`

## M3A adds

Backend router:

```text
/api/live-shadow/midpoint-strategy/status
/api/live-shadow/midpoint-strategy/events
/api/live-shadow/midpoint-strategy/timeline
/api/live-shadow/midpoint-strategy/audit-detail?event_id=...
```

Audit source:

```text
data/live-observation/midpoint-strategy-v1/audit.jsonl
```

Frontend workspace:

```text
Midpoint Strategy
```

The workspace reuses the existing application CSS/layout patterns and exposes:

- Family B state
- B entry
- +20 proof
- runner classification
- degraded / recovery
- CAP20 rescue
- post-rescue re-entry
- reference type / midpoint / boundary
- underlying / directional points / directional VWAP
- Family B/C/D/PM-E rollout status
- safety flags
- inspectable audit timeline

## Safe patching

`scripts/apply_midpoint_m3_workspace.py` patches only known anchors in:

- `backend/market_lab/api.py`
- `frontend/src/App.tsx`

Run dry first. It refuses to patch when expected anchors are not unique.

## M3B shared worker wiring

M3A does not start or duplicate a worker.

Before wiring the Midpoint engine into `live_shadow_worker_v1.py`, run:

```bash
python scripts/midpoint_m3_runtime_preflight.py
```

This prints the real coordinator/source method signatures without broker calls.
Use that output for M3B so we share the current Hilega worker/data adapters rather
than inventing parallel runtime machinery.

Safety remains:

```text
observation_only=true
execution_enabled=false
paper_order_enabled=false
quantity=None
```
