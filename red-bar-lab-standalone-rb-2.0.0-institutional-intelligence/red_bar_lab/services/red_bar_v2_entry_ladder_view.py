"""Assemble one Red Bar V2 candidate's walk down the 21 entry checkpoints.

Pure read. This module runs no gate, writes no row and changes no decision -- it
joins three stores that are each keyed by a different stage of a signal's life
and presents them as the single ordered sequence the strategy actually evaluated:

    process_evidence.run_id -> signal_attempts.run_id / signal_id
                            -> execution_state_events.signal_id

``process_evidence`` answers the admission half (checkpoints 1-12),
``execution_state_events`` answers the order path (13-21), and
``signal_attempts`` is both the bridge between them and the record of the
risk plan frozen at admission.

A checkpoint with no recorded answer renders NOT_REACHED. It is never inferred
to have passed: the whole point of the screen is to say where the candidate
stopped, and a fabricated pass moves the stopping point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from red_bar_lab.execution.opportunity_engine import SHADOW_ENTRY_WARNINGS_PREFIX
from red_bar_lab.services.red_bar_v2_entry_ladder_catalog import (
    ADMISSION_PHASE,
    ADMITTING_CODES,
    ENTRY_LADDER,
    EVIDENCE_ONLY_STEPS,
    EntryCheckpoint,
    admission_checkpoints,
    checkpoint_for_code,
    order_path_checkpoints,
)


#: The process name ``record_strategy_subcheck`` writes every gate row under.
STRATEGY_PROCESS_NAME = "red_bar_v2_strategy"

STATE_OK = "ok"
STATE_FAIL = "FAIL"
STATE_NOT_REACHED = "NOT_REACHED"
STATE_NOT_APPLICABLE = "NA"

#: Risk-plan codes that mean no plan was attempted, as against one that was
#: attempted and refused. The difference is checkpoint 12 reading NOT_REACHED
#: rather than FAIL, and it matters: an unattempted plan is not a rejected one.
_RISK_PLAN_ABSENT_CODES = frozenset(
    {"NO_ADMITTED_ENTRY", "RISK_PLAN_UNAVAILABLE", "", "None"}
)

@dataclass(frozen=True)
class LadderRow:
    """One checkpoint's verdict for one candidate.

    ``state`` is one of the four module constants. ``detail`` is the deciding
    numbers, already keyed for display -- the row does not know how to format
    them and the page does not know which ones matter.
    """

    number: int
    key: str
    title: str
    phase: str
    state: str
    code: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    recorded_at: str | None = None

    @property
    def is_stop(self) -> bool:
        return self.state == STATE_FAIL


@dataclass(frozen=True)
class EvidenceNote:
    """Something recorded that did not gate the entry.

    Two sources feed this: the demoted structure checks carried in the
    opportunity reason's ``SHADOW_ENTRY_WARNINGS`` token, and the evidence-only
    ``check:*`` steps. Neither can ever produce a FAIL on the ladder.
    """

    code: str
    source: str
    detail: str = ""
    recorded_at: str | None = None


@dataclass(frozen=True)
class LadderSignal:
    """One candidate and its full walk."""

    signal_id: str | None
    run_id: str | None
    label: str
    entry_timestamp: str | None
    direction: str | None
    entry_type: str | None
    option_side: str | None
    governing_reference: str | None
    governing_midpoint: float | None
    risk_stop_price: float | None
    risk_points: float | None
    risk_stop_trigger: str | None
    risk_plan_code: str | None
    admission_code: str | None
    candidate_allowed: bool | None
    rows: tuple[LadderRow, ...]
    evidence_only: tuple[EvidenceNote, ...]
    evidence_rows: tuple[Mapping[str, Any], ...] = ()
    state_events: tuple[Mapping[str, Any], ...] = ()

    @property
    def stopped_at(self) -> LadderRow | None:
        """The first checkpoint that refused this candidate, if any."""
        for row in self.rows:
            if row.state == STATE_FAIL:
                return row
        return None

    @property
    def reached_number(self) -> int:
        """The highest checkpoint number this candidate got an answer for."""
        answered = [
            row.number
            for row in self.rows
            if row.state in (STATE_OK, STATE_FAIL)
        ]
        return max(answered) if answered else 0


@dataclass(frozen=True)
class EntryLadderView:
    """Every candidate found for one instrument on one trading date."""

    trading_date: str
    instrument_key: str
    signals: tuple[LadderSignal, ...]
    cycle: Mapping[str, Any]
    selected_signal_id: str | None = None

    @property
    def selected(self) -> LadderSignal | None:
        if not self.signals:
            return None
        if self.selected_signal_id is not None:
            for signal in self.signals:
                if signal.signal_id == self.selected_signal_id:
                    return signal
        return self.signals[0]

def parse_shadow_warnings(reason: str | None) -> tuple[str, ...]:
    """The demoted codes carried in one opportunity reason string.

    Split on ``|`` first and keep only the ``SHADOW_ENTRY_WARNINGS`` token, then
    split *that token alone* on commas. Splitting the whole reason on commas
    picks up fragments of every other token and invents codes that were never
    recorded -- the bug this screen exists partly to make visible.
    """
    if not reason:
        return ()
    codes: list[str] = []
    for token in str(reason).split("|"):
        token = token.strip()
        if not token.startswith(SHADOW_ENTRY_WARNINGS_PREFIX):
            continue
        payload = token[len(SHADOW_ENTRY_WARNINGS_PREFIX):]
        for code in payload.split(","):
            code = code.strip()
            if code and code not in codes:
                codes.append(code)
    return tuple(codes)


def _blocking_part(detail: str | None) -> str:
    """``detail`` with the demoted-code token removed.

    Order-path checkpoint 17 is recognised by looking for its tokens inside a
    reason string. Scanning the raw string would let a code that was
    deliberately stripped of authority produce a FAIL, so the shadow token is
    dropped before any token match.
    """
    if not detail:
        return ""
    kept = [
        token
        for token in str(detail).split("|")
        if not token.strip().startswith(SHADOW_ENTRY_WARNINGS_PREFIX)
    ]
    return "|".join(kept)


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "ok"):
        return True
    if text in ("false", "0", "no", "error"):
        return False
    return None


def _artifacts(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not row:
        return {}
    artifacts = row.get("artifacts")
    return artifacts if isinstance(artifacts, Mapping) else {}


def _detail_source(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """One flat mapping of everything a gate row recorded.

    ``conditions`` is the policy's own dict, carried whole on the admission
    decision. Top-level artifact keys win over it, because a gate that recorded
    its own reading of a value recorded the one it actually used.
    """
    artifacts = _artifacts(row)
    flat: dict[str, Any] = {}
    conditions = artifacts.get("conditions")
    if isinstance(conditions, Mapping):
        flat.update(conditions)
    for key, value in artifacts.items():
        if key != "conditions":
            flat[key] = value
    return flat


def _detail_for(
    checkpoint: EntryCheckpoint, source: Mapping[str, Any]
) -> dict[str, Any]:
    """The deciding numbers this checkpoint declares, where they were recorded."""
    return {
        key: source[key]
        for key in checkpoint.detail_keys
        if key in source and source[key] is not None
    }

def _admission_stop_number(
    admission_code: str | None, candidate_allowed: bool | None
) -> int:
    """Which admission rung refused the candidate.

    Returns 0 when nothing was recorded -- no answer at all, so no rung may be
    called passed. Returns one past the ladder when the candidate was admitted,
    because clearing a strict priority chain means every rung before the
    terminal code was satisfied.
    """
    if candidate_allowed is True:
        return len(ENTRY_LADDER) + 1
    code = str(admission_code or "").strip()
    if not code:
        return 0
    checkpoint = checkpoint_for_code(code)
    if checkpoint is None or checkpoint.phase != ADMISSION_PHASE:
        return len(ENTRY_LADDER) + 1
    return checkpoint.number


def _admission_rows(
    *,
    evidence_by_step: Mapping[str, Mapping[str, Any]],
    admission_code: str | None,
    candidate_allowed: bool | None,
    entry_type: str | None,
    risk_plan: Mapping[str, Any],
) -> tuple[LadderRow, ...]:
    """Checkpoints 1-12 for one candidate.

    The admission half is a priority chain, so its verdict is one number: the
    rung that returned. Rungs below it passed, the rung itself failed, rungs
    above it were never consulted -- and a boolean recorded for one of those is
    stale rather than a verdict, which is why a row's own ``reached`` stamp can
    demote it but never promote it.
    """
    decision_source = _detail_source(evidence_by_step.get("admission_decision"))
    stop = _admission_stop_number(admission_code, candidate_allowed)
    rows: list[LadderRow] = []
    for checkpoint in admission_checkpoints():
        own_row = evidence_by_step.get(checkpoint.evidence_step or "")
        own_source = _detail_source(own_row)
        merged = {**decision_source, **own_source}
        detail = _detail_for(checkpoint, merged)
        recorded_at = str(own_row.get("started_at") or "") or None if own_row else None
        code: str | None = None

        if not checkpoint.applies_to_entry_type(entry_type):
            state = STATE_NOT_APPLICABLE
        elif checkpoint.number == 12:
            state, code = _risk_plan_state(
                checkpoint, candidate_allowed=candidate_allowed, risk_plan=risk_plan
            )
            detail = _detail_for(checkpoint, {**merged, **risk_plan})
        elif stop:
            if checkpoint.number < stop:
                state = STATE_OK
            elif checkpoint.number == stop:
                state = STATE_FAIL
                code = str(admission_code or "").strip() or None
            else:
                state = STATE_NOT_REACHED
        elif own_row is not None:
            # No admission decision recorded -- rows written before the ladder
            # existed. Their own status is the only answer available.
            reached = _as_bool(own_source.get("reached"))
            if reached is False:
                state = STATE_NOT_REACHED
            elif str(own_row.get("status") or "").upper() == "OK":
                state = STATE_OK
            else:
                state = STATE_FAIL
                code = ",".join(checkpoint.blocking_codes) or None
        else:
            state = STATE_NOT_REACHED

        rows.append(
            LadderRow(
                number=checkpoint.number,
                key=checkpoint.key,
                title=checkpoint.title,
                phase=checkpoint.phase,
                state=state,
                code=code,
                detail=detail,
                recorded_at=recorded_at,
            )
        )
    return tuple(rows)


def _risk_plan_state(
    checkpoint: EntryCheckpoint,
    *,
    candidate_allowed: bool | None,
    risk_plan: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Checkpoint 12, which is answered by ``signal_attempts`` rather than a gate row.

    A refused candidate never reaches it: the risk plan is priced against the
    admitted entry, so reporting the last plan on a row that was not admitted
    would describe a different trade.
    """
    if candidate_allowed is not True:
        return STATE_NOT_REACHED, None
    code = str(risk_plan.get("risk_plan_code") or "").strip()
    if code in checkpoint.blocking_codes:
        return STATE_FAIL, code
    tradable = _as_bool(risk_plan.get("risk_plan_tradable"))
    if tradable is True:
        return STATE_OK, None
    if tradable is False:
        return STATE_FAIL, code or "RISK_PLAN_REJECTED"
    if (
        risk_plan.get("risk_stop_price") is not None
        and risk_plan.get("risk_points") is not None
    ):
        return STATE_OK, None
    return STATE_NOT_REACHED, None

def _event_detail(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "state": event.get("state"),
        "detail": event.get("detail"),
        "timestamp": event.get("timestamp"),
    }


def _order_path_rows(events: Sequence[Mapping[str, Any]]) -> tuple[LadderRow, ...]:
    """Checkpoints 13-21 for one candidate, from its lifecycle events.

    Unlike the admission half this is not a single verdict but a trail, so each
    rung is answered independently: a recorded pass state clears it, a recorded
    blocking state or an in-reason token refuses it, and silence leaves it
    unreached.

    Three rungs record no pass state of their own -- capacity, freshness and the
    order path's own view of the risk plan are only ever written when they
    refuse. Those are cleared by proof of progress: a later rung that did record
    a pass, with no refusal in between. That is derivation from the trail, not a
    guess, and it stops at the first refusal.
    """
    pass_at: dict[int, Mapping[str, Any]] = {}
    block_at: dict[int, tuple[str, Mapping[str, Any]]] = {}
    for checkpoint in order_path_checkpoints():
        for event in events:
            state = str(event.get("state") or "").strip().upper()
            if checkpoint.reason_tokens:
                haystack = _blocking_part(str(event.get("detail") or "")).upper()
                hit = next(
                    (
                        token
                        for token in checkpoint.reason_tokens
                        if token.upper() in haystack
                    ),
                    None,
                )
                if hit is not None:
                    block_at.setdefault(checkpoint.number, (hit, event))
                    break
            if state and state in checkpoint.pass_states:
                pass_at.setdefault(checkpoint.number, event)
                break
            if state and state in checkpoint.blocking_codes:
                block_at.setdefault(checkpoint.number, (state, event))
                break

    highest_pass = max(pass_at, default=0)
    stop = min(block_at, default=None)

    rows: list[LadderRow] = []
    for checkpoint in order_path_checkpoints():
        number = checkpoint.number
        if number in block_at:
            code, event = block_at[number]
            rows.append(
                _order_row(checkpoint, STATE_FAIL, code=code, event=event)
            )
            continue
        if number in pass_at:
            rows.append(
                _order_row(checkpoint, STATE_OK, event=pass_at[number])
            )
            continue
        derived = (
            not checkpoint.pass_states
            and number < highest_pass
            and (stop is None or number < stop)
        )
        rows.append(
            _order_row(checkpoint, STATE_OK if derived else STATE_NOT_REACHED)
        )
    return tuple(rows)


def _order_row(
    checkpoint: EntryCheckpoint,
    state: str,
    *,
    code: str | None = None,
    event: Mapping[str, Any] | None = None,
) -> LadderRow:
    return LadderRow(
        number=checkpoint.number,
        key=checkpoint.key,
        title=checkpoint.title,
        phase=checkpoint.phase,
        state=state,
        code=code,
        detail=_event_detail(event) if event is not None else {},
        recorded_at=str(event.get("timestamp") or "") or None if event else None,
    )


def _evidence_notes(
    *,
    evidence_by_step: Mapping[str, Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
) -> tuple[EvidenceNote, ...]:
    """What was recorded and given no authority over the entry.

    Two sources: the ``check:*`` steps that exist purely as evidence, and the
    demoted structure codes carried in an opportunity reason. Neither can
    produce a rung, so neither can produce a FAIL.
    """
    notes: list[EvidenceNote] = []
    for step in EVIDENCE_ONLY_STEPS:
        row = evidence_by_step.get(step)
        if row is None:
            continue
        source = _detail_source(row)
        detail = ", ".join(
            f"{key}={value}"
            for key, value in source.items()
            if key not in ("checkpoint", "reached", "candidate_allowed")
        )
        notes.append(
            EvidenceNote(
                code=step.split(":", 1)[-1].upper(),
                source="evidence_step",
                detail=detail,
                recorded_at=str(row.get("started_at") or "") or None,
            )
        )
    seen: set[str] = set()
    for event in events:
        for code in parse_shadow_warnings(str(event.get("detail") or "")):
            if code in seen:
                continue
            seen.add(code)
            notes.append(
                EvidenceNote(
                    code=code,
                    source="shadow_entry_warning",
                    detail=f"recorded on {event.get('state') or 'event'}",
                    recorded_at=str(event.get("timestamp") or "") or None,
                )
            )
    return tuple(notes)

def _evidence_by_step(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Index one run's evidence rows by step name, latest occurrence winning.

    ``read_run_evidence`` returns rows oldest-first, so a plain overwrite keeps
    the last answer a step gave inside the run.
    """
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        step = str(row.get("step_name") or "")
        if step:
            indexed[step] = row
    return indexed


def _reference_matches(
    evidence_by_step: Mapping[str, Mapping[str, Any]], attempt: Mapping[str, Any]
) -> bool:
    """Whether a run's admission evidence describes this attempt.

    One run can in principle hold more than one admission, and attaching the
    wrong one silently relabels which reference the gates were judged against.
    Compared to the minute, because the two stores stamp seconds differently.
    """
    reference = str(
        _detail_source(evidence_by_step.get("admission_decision")).get(
            "reference_timestamp"
        )
        or ""
    )
    cross = str(attempt.get("cross_timestamp") or "")
    if not reference or not cross:
        return True
    return reference == cross or reference[:16] == cross[:16]


def _cycle_summary(
    *,
    trading_date: str,
    run_id: str | None,
    evidence_by_step: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The thin strip above the ladder: what the newest cycle saw."""
    scan = _artifacts(evidence_by_step.get("candidate_scan"))
    decision = _detail_source(evidence_by_step.get("admission_decision"))
    row = evidence_by_step.get("admission_decision") or evidence_by_step.get(
        "candidate_scan"
    )
    return {
        "trading_date": trading_date,
        "run_id": run_id,
        "evaluated_at": str(row.get("started_at") or "") or None if row else None,
        "candidate_count": scan.get("candidate_count"),
        "candidate_event_types": scan.get("candidate_event_types"),
        "context_timestamp": decision.get("context_timestamp"),
        "reference_timestamp": decision.get("reference_timestamp"),
        "governing_reference": decision.get("governing_reference"),
        "direction": decision.get("direction"),
        "entry_type": decision.get("entry_type"),
        "admission_code": decision.get("admission_code"),
        "admission_reason": decision.get("admission_reason"),
        "candidate_allowed": _as_bool(decision.get("candidate_allowed")),
        "active_trade_count": decision.get("active_trade_count"),
        "trade_state": decision.get("trade_state"),
    }


def _signal_label(
    *,
    entry_timestamp: str | None,
    direction: str | None,
    entry_type: str | None,
    signal_id: str | None,
    run_id: str | None,
) -> str:
    stamp = (entry_timestamp or "")[11:16] or (entry_timestamp or "") or "--:--"
    parts = [stamp]
    if entry_type:
        parts.append(str(entry_type))
    if direction:
        parts.append(str(direction))
    tail = signal_id or run_id
    if tail:
        parts.append(str(tail)[-8:])
    return "  ".join(parts)

def _collect_run_ids(
    database: Any, *, trading_date: str, attempts: Sequence[Mapping[str, Any]], limit: int
) -> list[str]:
    """Every strategy run worth reading for one date, newest first.

    Three sources, because a run can appear in any one of them alone: runs that
    recorded an admission decision, the newest run that only scanned (so a cycle
    with no candidate at all still fills the strip), and runs named by a signal
    attempt whose evidence was pruned.
    """
    run_ids: list[str] = []

    def _add(rows: Sequence[Mapping[str, Any]]) -> None:
        for row in rows:
            run_id = str(row.get("run_id") or "")
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)

    for step, step_limit in (("admission_decision", limit), ("candidate_scan", 1)):
        _add(
            database.read_evidence_run_ids(
                process_name=STRATEGY_PROCESS_NAME,
                step_name=step,
                date_prefix=trading_date,
                limit=step_limit,
            )
        )
    _add([{"run_id": attempt.get("run_id")} for attempt in attempts])
    return run_ids[:limit]


def build_entry_ladder_view(
    database: Any,
    *,
    trading_date: str,
    instrument_key: str,
    signal_id: str | None = None,
    max_runs: int = 60,
) -> EntryLadderView:
    """Every Red Bar V2 candidate for one instrument on one date, as ladders.

    Reads only. ``max_runs`` bounds the evidence read so a date with hundreds of
    cycles cannot turn one page load into a full table scan; the newest runs are
    the ones worth reading.
    """
    attempts = list(
        database.read_signal_attempts_range(instrument_key, trading_date, trading_date)
    )
    run_ids = _collect_run_ids(
        database, trading_date=trading_date, attempts=attempts, limit=max_runs
    )

    evidence: dict[str, dict[str, Mapping[str, Any]]] = {}
    raw_rows: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for run_id in run_ids:
        rows = list(database.read_run_evidence(run_id=run_id))
        evidence[run_id] = _evidence_by_step(rows)
        raw_rows[run_id] = tuple(rows)

    attempt_ids = [
        str(attempt.get("signal_id") or "")
        for attempt in attempts
        if attempt.get("signal_id")
    ]
    events_by_signal = (
        database.read_execution_state_events_for_signals(attempt_ids)
        if attempt_ids
        else {}
    )

    signals: list[LadderSignal] = []
    claimed_runs: set[str] = set()
    attempts_per_run: dict[str, int] = {}
    for attempt in attempts:
        run_id = str(attempt.get("run_id") or "")
        attempts_per_run[run_id] = attempts_per_run.get(run_id, 0) + 1

    for attempt in attempts:
        run_id = str(attempt.get("run_id") or "")
        by_step = evidence.get(run_id, {})
        if by_step and attempts_per_run.get(run_id, 0) > 1:
            if not _reference_matches(by_step, attempt):
                by_step = {}
        if by_step:
            claimed_runs.add(run_id)
        signals.append(
            _signal_from_attempt(
                attempt,
                by_step=by_step,
                events=events_by_signal.get(str(attempt.get("signal_id") or ""), ()),
                raw_rows=raw_rows.get(run_id, ()) if by_step else (),
            )
        )

    for run_id in run_ids:
        if run_id in claimed_runs:
            continue
        by_step = evidence.get(run_id, {})
        if "admission_decision" not in by_step:
            continue
        signals.append(
            _signal_from_evidence(
                run_id, by_step=by_step, raw_rows=raw_rows.get(run_id, ())
            )
        )

    signals.sort(key=lambda item: (item.entry_timestamp or "", item.label), reverse=True)

    newest_run = run_ids[0] if run_ids else None
    cycle = _cycle_summary(
        trading_date=trading_date,
        run_id=newest_run,
        evidence_by_step=evidence.get(newest_run or "", {}),
    )
    return EntryLadderView(
        trading_date=trading_date,
        instrument_key=instrument_key,
        signals=tuple(signals),
        cycle=cycle,
        selected_signal_id=signal_id,
    )

def _resolved_allowed(
    decision: Mapping[str, Any], admission_code: str | None
) -> bool | None:
    """Whether the candidate was admitted, from the row or from its code.

    Rows written before ``candidate_allowed`` was stamped still name their
    terminal code, and the admitting codes are enumerated -- so the answer is
    recoverable rather than unknown.
    """
    allowed = _as_bool(decision.get("candidate_allowed"))
    if allowed is not None:
        return allowed
    if admission_code:
        return admission_code in ADMITTING_CODES
    return None


def _signal_from_attempt(
    attempt: Mapping[str, Any],
    *,
    by_step: Mapping[str, Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    raw_rows: Sequence[Mapping[str, Any]],
) -> LadderSignal:
    decision = _detail_source(by_step.get("admission_decision"))
    ordered = tuple(sorted(events, key=lambda item: str(item.get("timestamp") or "")))
    admission_code = str(decision.get("admission_code") or "") or None
    candidate_allowed = _resolved_allowed(decision, admission_code)
    entry_type = (
        str(attempt.get("entry_type") or decision.get("entry_type") or "") or None
    )
    risk_plan = {
        "risk_plan_code": attempt.get("risk_plan_code"),
        "risk_plan_tradable": attempt.get("risk_plan_tradable"),
        "risk_stop_price": attempt.get("risk_stop_price"),
        "risk_points": attempt.get("risk_points"),
        "risk_stop_trigger": attempt.get("risk_stop_trigger"),
    }
    entry_timestamp = (
        str(attempt.get("confirmation_timestamp") or "")
        or str(attempt.get("cross_timestamp") or "")
        or None
    )
    signal_id = str(attempt.get("signal_id") or "") or None
    run_id = str(attempt.get("run_id") or "") or None
    direction = str(attempt.get("direction") or decision.get("direction") or "") or None
    rows = _admission_rows(
        evidence_by_step=by_step,
        admission_code=admission_code,
        candidate_allowed=candidate_allowed,
        entry_type=entry_type,
        risk_plan=risk_plan,
    ) + _order_path_rows(ordered)
    return LadderSignal(
        signal_id=signal_id,
        run_id=run_id,
        label=_signal_label(
            entry_timestamp=entry_timestamp,
            direction=direction,
            entry_type=entry_type,
            signal_id=signal_id,
            run_id=run_id,
        ),
        entry_timestamp=entry_timestamp,
        direction=direction,
        entry_type=entry_type,
        option_side=str(decision.get("option_side") or "") or None,
        governing_reference=str(
            attempt.get("governing_reference")
            or decision.get("governing_reference")
            or ""
        )
        or None,
        governing_midpoint=attempt.get("governing_midpoint"),
        risk_stop_price=attempt.get("risk_stop_price"),
        risk_points=attempt.get("risk_points"),
        risk_stop_trigger=str(attempt.get("risk_stop_trigger") or "") or None,
        risk_plan_code=str(attempt.get("risk_plan_code") or "") or None,
        admission_code=admission_code,
        candidate_allowed=candidate_allowed,
        rows=rows,
        evidence_only=_evidence_notes(evidence_by_step=by_step, events=ordered),
        evidence_rows=tuple(raw_rows),
        state_events=ordered,
    )


def _signal_from_evidence(
    run_id: str,
    *,
    by_step: Mapping[str, Mapping[str, Any]],
    raw_rows: Sequence[Mapping[str, Any]],
) -> LadderSignal:
    """A candidate that produced gate evidence and never became an attempt.

    This is the common case and the reason the screen exists: a refusal leaves a
    run_id and a full set of gate rows, but no signal_id, no order and nothing in
    any other table to look at.
    """
    row = by_step.get("admission_decision")
    decision = _detail_source(row)
    admission_code = str(decision.get("admission_code") or "") or None
    candidate_allowed = _resolved_allowed(decision, admission_code)
    entry_type = str(decision.get("entry_type") or "") or None
    direction = str(decision.get("direction") or "") or None
    entry_timestamp = (
        str(decision.get("context_timestamp") or "")
        or (str(row.get("started_at") or "") if row else "")
        or None
    )
    rows = _admission_rows(
        evidence_by_step=by_step,
        admission_code=admission_code,
        candidate_allowed=candidate_allowed,
        entry_type=entry_type,
        risk_plan={},
    ) + _order_path_rows(())
    return LadderSignal(
        signal_id=None,
        run_id=run_id,
        label=_signal_label(
            entry_timestamp=entry_timestamp,
            direction=direction,
            entry_type=entry_type,
            signal_id=None,
            run_id=run_id,
        ),
        entry_timestamp=entry_timestamp,
        direction=direction,
        entry_type=entry_type,
        option_side=str(decision.get("option_side") or "") or None,
        governing_reference=str(decision.get("governing_reference") or "") or None,
        governing_midpoint=decision.get("governing_midpoint"),
        risk_stop_price=None,
        risk_points=None,
        risk_stop_trigger=None,
        risk_plan_code=None,
        admission_code=admission_code,
        candidate_allowed=candidate_allowed,
        rows=rows,
        evidence_only=_evidence_notes(evidence_by_step=by_step, events=()),
        evidence_rows=tuple(raw_rows),
        state_events=(),
    )

