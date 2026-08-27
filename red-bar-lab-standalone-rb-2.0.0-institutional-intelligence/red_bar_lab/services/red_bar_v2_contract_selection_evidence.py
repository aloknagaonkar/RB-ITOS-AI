from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path


FILENAME = "red_bar_v2_contract_selection_evidence.json"


@dataclass(frozen=True, slots=True)
class ContractCandidateEvidence:
    rank: int
    symbol: str
    instrument_token: int
    option_type: str
    strike: float
    expiry: str
    lot_size: int
    total_score: float
    minimum_score: float
    score_eligible: bool
    spread_score: float
    liquidity_score: float
    volume_score: float
    oi_score: float
    vwap_score: float
    ema_score: float
    momentum_score: float
    momentum_pct: float | None
    candle_count: int
    ltp: float | None
    best_bid: float | None
    best_ask: float | None
    evidence_detail: str


@dataclass(frozen=True, slots=True)
class ContractSelectionEvidence:
    correlation_id: str
    signal_id: str
    direction: str
    evaluated_at: str
    duration_ms: float
    candidates: tuple[ContractCandidateEvidence, ...]


def persist_contract_selection_evidence(
    artifacts_root: str | Path,
    evidence: tuple[ContractSelectionEvidence, ...],
    *,
    recorded_at: datetime,
) -> bool:
    """Persist the latest bounded selection projection after execution processing."""
    target = Path(artifacts_root) / "operations" / FILENAME
    temporary = target.with_suffix(".tmp")
    payload = {
        "schema_version": "RED_BAR_V2_CONTRACT_SELECTION_V1",
        "recorded_at": recorded_at.isoformat(),
        "selections": [asdict(item) for item in evidence],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        return False
    return True


def read_contract_selection_evidence(
    artifacts_root: str | Path,
) -> dict[str, object]:
    target = Path(artifacts_root) / "operations" / FILENAME
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "ContractCandidateEvidence",
    "ContractSelectionEvidence",
    "persist_contract_selection_evidence",
    "read_contract_selection_evidence",
]
