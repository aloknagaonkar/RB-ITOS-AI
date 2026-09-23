from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .hilega_milega_strategy_v1 import STRATEGY_ID, STRATEGY_VERSION
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = "HILEGA_MILEGA_LIVE_SHADOW_UI_V1"
DATA_DIR = Path("data/live-observation/hilega-milega-v1")
STEP_AUDIT_PATH = DATA_DIR / "step-audit.jsonl"
router = APIRouter(prefix="/api/live-shadow/hilega-milega", tags=["live-shadow-hilega-milega"])


def _store() -> ShadowStepAuditStoreV1:
    return ShadowStepAuditStoreV1(STEP_AUDIT_PATH)


def _rows() -> list[dict[str, Any]]:
    return _store().read_all() if STEP_AUDIT_PATH.exists() else []


@router.get("/status")
def status():
    rows = _rows()
    transitions = [x for x in rows if x.get("stage") == "STRATEGY_TRANSITION"]
    decisions = [x for x in rows if x.get("stage") == "STRATEGY_DECISION_RESULT"]
    store = _store()
    chain_ok, chain_issue = store.verify_chain() if STEP_AUDIT_PATH.exists() else (True, None)
    counts = Counter(x.get("status") for x in transitions)
    latest = decisions[-1] if decisions else None
    return {
        "model": MODEL,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "step_audit_present": STEP_AUDIT_PATH.exists(),
        "step_audit_chain_ok": chain_ok,
        "step_audit_chain_issue": chain_issue,
        "transition_counts": dict(counts),
        "latest_decision": latest,
    }


@router.get("/decision-audit")
def decision_audit(limit: int = 200):
    if limit < 1 or limit > 2000:
        raise HTTPException(422, "limit must be between 1 and 2000")
    rows = [x for x in _rows() if x.get("stage") in {"STRATEGY_DECISION", "STRATEGY_DECISION_RESULT", "STRATEGY_TRANSITION", "SESSION_CUTOFF_SOURCE"}]
    rows = rows[-limit:]
    rows.reverse()
    chain_ok, chain_issue = _store().verify_chain() if STEP_AUDIT_PATH.exists() else (True, None)
    return {"chain_ok": chain_ok, "chain_issue": chain_issue, "rows": rows}


@router.get("/transitions")
def transitions(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(422, "limit must be between 1 and 1000")
    rows = [x for x in _rows() if x.get("stage") == "STRATEGY_TRANSITION"][-limit:]
    rows.reverse()
    return rows
