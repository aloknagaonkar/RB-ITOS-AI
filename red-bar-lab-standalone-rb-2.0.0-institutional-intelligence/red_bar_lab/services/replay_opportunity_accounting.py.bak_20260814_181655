from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Any

class ReplayRowLike(Protocol):
    signal_id: str
    candidate_rank: int | None
    execution: str
    verdict: str
    outcome_result: str
    outcome_points: float | None

@dataclass(frozen=True)
class OpportunityReplaySummary:
    opportunity_rows: tuple[Any, ...]
    opportunities: int
    candidates_evaluated: int
    trades_selected: int
    would_take: int
    would_wait: int
    would_block: int
    winners: int
    losers: int
    correct_takes: int
    false_positives: int
    missed_opportunities: int
    correct_skips: int
    incorrect_blocks: int
    correct_blocks: int
    net_points: float
    decision_accuracy_pct: float

def _rank_key(row: ReplayRowLike) -> tuple[int, int]:
    rank = row.candidate_rank
    return (0 if rank is not None else 1, int(rank or 10**9))

def consolidate_replay_rows(rows: Iterable[ReplayRowLike]) -> OpportunityReplaySummary:
    materialized = tuple(rows)
    grouped = {}
    for row in materialized:
        grouped.setdefault(str(row.signal_id), []).append(row)
    selected = [sorted(items, key=_rank_key)[0] for items in grouped.values()]
    selected.sort(key=lambda row: str(getattr(row, 'timestamp', '')))
    def count(field, value):
        return sum(1 for row in selected if str(getattr(row, field, '')) == value)
    resolved=[r for r in selected if str(getattr(r,'verdict','')) not in {'','UNRESOLVED','NEUTRAL'}]
    correct=sum(1 for r in resolved if str(getattr(r,'verdict','')) in {'CORRECT_TAKE','CORRECT_SKIP','CORRECT_BLOCK'})
    accuracy=round(correct/len(resolved)*100.0,2) if resolved else 0.0
    return OpportunityReplaySummary(tuple(selected),len(selected),sum(1 for r in materialized if getattr(r,'candidate_rank',None) is not None),sum(1 for r in selected if str(getattr(r,'execution',''))=='WOULD_TAKE'),count('execution','WOULD_TAKE'),count('execution','WOULD_WAIT'),count('execution','WOULD_BLOCK'),count('outcome_result','WIN'),count('outcome_result','LOSS'),count('verdict','CORRECT_TAKE'),count('verdict','FALSE_POSITIVE'),count('verdict','MISSED_OPPORTUNITY'),count('verdict','CORRECT_SKIP'),count('verdict','INCORRECT_BLOCK'),count('verdict','CORRECT_BLOCK'),round(sum(float(getattr(r,'outcome_points',0.0) or 0.0) for r in selected),4),accuracy)
