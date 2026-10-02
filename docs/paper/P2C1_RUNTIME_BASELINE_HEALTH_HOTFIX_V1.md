# P2C.1 Runtime Baseline / Health Hotfix

The live smoke test exposed two production issues that unit tests could not reveal:

1. Config 6 was activated after 09:20, so there is no valid 09:20 baseline for today.
   This is a real prerequisite failure and MUST NOT be fabricated.
2. `paper_control.enabled=false` was authoritative, but `paper_health.paper_enabled=true`
   was stale merged health metadata from an earlier run.

A third improvement is included:
- evaluate only once per 5-minute checkpoint instead of once per 15-second observation.

## Today

Because config 6 began after 09:20, Strategy #2 should stay blocked for the rest of this
session unless a real compatible 09:20 observation already exists. Do not substitute 09:28
as the baseline and do not copy OI from another expiry.

Tomorrow, if collection is active before 09:20 and config 6 remains valid, the 09:20 baseline
will be recorded normally.

## Required tiny edit in `oi_vwap_causal_runtime_v1.py`

Add:

```python
from .oi_vwap_runtime_guards_v1 import classify_oi_feature_error, classify_p2_checkpoint
```

Replace the `except Exception as exc:` block around `build_oi_checkpoint_feature(...)`
so the reason code is classified:

```python
except Exception as exc:
    reason = classify_oi_feature_error(exc)
    record_event(
        session,
        event_type=reason,
        stage="FEATURES",
        status="FAIL",
        reason_code=reason,
        observation_id=observation_id,
        output_data={"detail": str(exc)},
    )
    return RuntimeDecision(
        "BLOCKED", reason, observation_id, None,
        None, None, False, {"detail": str(exc)}
    )
```

In the WAIT_P2 branch, before `_p2_persists(...)`, require the exact next checkpoint:

```python
p2_checkpoint = classify_p2_checkpoint(
    p1_time=waiting.p1_time,
    current_time=current.timestamp,
)

if p2_checkpoint == "TOO_EARLY":
    return RuntimeDecision(
        "WAIT_P2", None, observation_id, current.timestamp,
        waiting.id, waiting.direction, False, {"oi": asdict(current)}
    )

if p2_checkpoint == "P2_CHECKPOINT_MISSED":
    reject_waiting_signal(
        session,
        waiting,
        p2_observation_id=current.observation_id,
        p2_time=current.timestamp,
        reason_code="P2_CHECKPOINT_MISSED",
        evidence_update={"p2": asdict(current)},
    )
    return RuntimeDecision(
        "REJECTED", "P2_CHECKPOINT_MISSED", observation_id,
        current.timestamp, waiting.id, waiting.direction, False,
        {"oi": asdict(current)}
    )
```

## Replace service module

Replace:
`backend/market_lab/oi_vwap_causal_service_v1.py`

with the P2C.1 version in this bundle.

## Validation

Keep paper disabled.

```bash
python -m market_lab.paper_control_v1 disable
python -m pytest tests/test_p2c1_runtime_guards_v1.py -v
```

Then run:

```bash
python -m market_lab.oi_vwap_causal_service_v1
```

In a second shell:

```bash
python -m market_lab.paper_control_v1 status
python -m market_lab.paper_control_v1 detail --limit 20
```

Expected today:
- control.enabled=false
- health.paper_enabled=false
- strategy state BLOCKED
- reason SESSION_BASELINE_UNAVAILABLE
- at most one new feature failure event per 5-minute checkpoint
