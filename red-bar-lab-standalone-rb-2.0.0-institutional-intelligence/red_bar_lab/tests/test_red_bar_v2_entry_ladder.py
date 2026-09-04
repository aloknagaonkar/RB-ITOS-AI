"""The Red Bar V2 entry ladder: catalog, assembler and page.

These are property tests, not mirrors of the implementation. Each one states
something the screen must keep being true about the strategy, so that a rule
change which invalidates the screen fails here rather than quietly rendering a
ladder that describes gates the strategy no longer runs.
"""

from __future__ import annotations

import inspect
import json
import re
import sqlite3
from types import SimpleNamespace

from red_bar_lab.execution import red_bar_v2_admission_policy as policy
from red_bar_lab.execution.red_bar_v2_admission_policy import AdmissionCode
from red_bar_lab.services.red_bar_v2_current_session import _ranked_admission
from red_bar_lab.services.red_bar_v2_entry_ladder_catalog import (
    ADMISSION_PHASE,
    CONTEXT_EVENT_STATES,
    ENTRY_LADDER,
    ORDER_PATH_PHASE,
    RETIRED_ADMISSION_CODES,
    admission_checkpoints,
    checkpoint_for_code,
    order_path_checkpoints,
    order_path_event_states,
)
from red_bar_lab.services.red_bar_v2_entry_ladder_view import (
    STATE_FAIL,
    STATE_NOT_APPLICABLE,
    STATE_NOT_REACHED,
    STATE_OK,
    build_entry_ladder_view,
    parse_shadow_warnings,
)
from red_bar_lab.storage.database import RedBarDatabase


def _gate_row(step: str, status: str, artifacts: dict, at: str) -> dict:
    return {
        "step_name": step,
        "status": status,
        "started_at": at,
        "artifacts": dict(artifacts),
    }


def _decision_row(
    *,
    code: str,
    allowed: bool,
    at: str = "2026-09-03T11:42:00",
    entry_type: str | None = None,
    conditions: dict | None = None,
    extra: dict | None = None,
) -> dict:
    artifacts = {
        "admission_code": code,
        "candidate_allowed": allowed,
        "reference_timestamp": "2026-09-03T11:30:00",
        "context_timestamp": at,
        "conditions": dict(conditions or {}),
    }
    if entry_type:
        artifacts["entry_type"] = entry_type
    artifacts.update(extra or {})
    return _gate_row("admission_decision", "OK" if allowed else "ERROR", artifacts, at)


class FakeLadderDatabase:
    """The three read helpers the assembler composes, and nothing else.

    A fake rather than a real database because the assembler's contract is those
    three reads; the one piece of genuinely new SQL is covered against a real
    database further down.
    """

    def __init__(
        self,
        *,
        attempts: list[dict] | None = None,
        evidence: dict[str, list[dict]] | None = None,
        events: dict[str, list[dict]] | None = None,
        run_order: list[str] | None = None,
    ) -> None:
        self.attempts = attempts or []
        self.evidence = evidence or {}
        self.events = events or {}
        self.run_order = run_order or list(self.evidence)
        self.evidence_reads: list[str] = []

    def read_signal_attempts_range(self, instrument_key, date_from, date_to):
        return [
            row
            for row in self.attempts
            if str(row.get("trading_date")) >= date_from
            and str(row.get("trading_date")) <= date_to
        ]

    def read_evidence_run_ids(
        self,
        *,
        process_name,
        step_name,
        date_prefix=None,
        artifact_contains=None,
        limit=200,
    ):
        matches = [
            run_id
            for run_id in self.run_order
            if any(
                str(row.get("step_name")) == step_name
                and (
                    date_prefix is None
                    or str(row.get("started_at") or "").startswith(date_prefix)
                )
                and (
                    artifact_contains is None
                    or artifact_contains in json.dumps(row.get("artifacts") or {})
                )
                for row in self.evidence.get(run_id, [])
            )
        ]
        return [{"run_id": run_id} for run_id in matches[:limit]]

    def read_run_evidence(self, *, run_id):
        self.evidence_reads.append(run_id)
        return list(self.evidence.get(run_id, []))

    def read_execution_state_events_for_signals(
        self,
        signal_ids,
        *,
        per_signal_limit=50,
        oldest_first=False,
        states=None,
        per_state_limit=None,
    ):
        wanted = {str(item) for item in (states or ())}
        result = {}
        for signal_id in signal_ids:
            rows = [
                event
                for event in self.events.get(str(signal_id), [])
                if not wanted or str(event.get("state") or "") in wanted
            ]
            rows.sort(
                key=lambda event: str(event.get("timestamp") or ""),
                reverse=not oldest_first,
            )
            if per_state_limit is not None:
                seen: dict[str, int] = {}
                kept = []
                for event in rows:
                    key = str(event.get("state") or "")
                    seen[key] = seen.get(key, 0) + 1
                    if seen[key] <= max(1, int(per_state_limit)):
                        kept.append(event)
                rows = kept
            else:
                rows = rows[:max(1, int(per_signal_limit))]
            result[str(signal_id)] = rows
        return result


def _states(signal) -> dict[int, str]:
    return {row.number: row.state for row in signal.rows}

def test_catalog_order_matches_the_policy_return_order() -> None:
    """The ladder is the order the policy actually returns codes in.

    ``AdmissionCode`` is declared grouped by kind, not by precedence, so the
    enum cannot be the source of order -- ``CONTEXT_STALE`` is declared
    thirteenth and evaluated second. Scanning the policy's own source keeps a
    reordered gate from silently mis-naming which check stopped a trade.
    """
    source = inspect.getsource(policy.evaluate_candidate_admission)
    blocking = {
        code
        for checkpoint in admission_checkpoints()
        for code in checkpoint.blocking_codes
    }
    seen: list[str] = []
    for name in re.findall(r"AdmissionCode\.([A-Z_0-9]+)", source):
        value = AdmissionCode[name].value
        if value in blocking and value not in seen:
            seen.append(value)
    expected = [
        code
        for checkpoint in admission_checkpoints()
        for code in checkpoint.blocking_codes
        if code in {item.value for item in AdmissionCode}
    ]
    assert seen == expected


def test_every_admission_code_is_either_a_rung_or_declared_terminal() -> None:
    """A gate added to the policy cannot fail to appear on the screen."""
    from red_bar_lab.services.red_bar_v2_entry_ladder_catalog import ADMITTING_CODES

    accounted = (
        {code for checkpoint in ENTRY_LADDER for code in checkpoint.blocking_codes}
        | set(ADMITTING_CODES)
        | set(RETIRED_ADMISSION_CODES)
    )
    missing = sorted(
        item.value for item in AdmissionCode if item.value not in accounted
    )
    assert missing == []


def test_ladder_is_contiguous_and_each_code_owns_one_rung() -> None:
    numbers = [checkpoint.number for checkpoint in ENTRY_LADDER]
    assert numbers == list(range(1, len(ENTRY_LADDER) + 1))
    assert len({checkpoint.key for checkpoint in ENTRY_LADDER}) == len(ENTRY_LADDER)
    codes = [code for checkpoint in ENTRY_LADDER for code in checkpoint.blocking_codes]
    assert len(codes) == len(set(codes))
    assert [c.phase for c in admission_checkpoints()] == [ADMISSION_PHASE] * 12
    assert [c.phase for c in order_path_checkpoints()] == [ORDER_PATH_PHASE] * 9


def test_order_path_states_still_exist_in_the_execution_source() -> None:
    """A renamed lifecycle state fails here, not as a permanently blank rung.

    The order-path half has no enum to derive from, so the literals are pinned
    against the module that writes them.
    """
    from red_bar_lab.execution import automation

    source = inspect.getsource(automation)
    for checkpoint in order_path_checkpoints():
        for state in checkpoint.pass_states + checkpoint.blocking_codes:
            assert state in source, f"{checkpoint.key} references missing {state}"


def test_refused_candidate_produces_a_ladder_that_names_the_midpoint_gate() -> None:
    """The assertion the whole screen exists for.

    A cycle that admitted nothing still walked nine checkpoints. Before the gate
    evidence was recorded for refusals this could not be answered at all.
    """
    evidence = {
        "run-a": [
            _gate_row("candidate_scan", "OK", {"candidate_count": 1}, "2026-09-03T11:42:00"),
            _decision_row(
                code=AdmissionCode.MIDPOINT_NOT_ALIGNED.value,
                allowed=False,
                conditions={"midpoint_aligned": False, "index_close": 23960.0},
            ),
            _gate_row(
                "check:midpoint_aligned",
                "ERROR",
                {"checkpoint": 10, "reached": True, "reference_midpoint": 24000.0},
                "2026-09-03T11:42:00",
            ),
        ]
    }
    view = build_entry_ladder_view(
        FakeLadderDatabase(evidence=evidence),
        trading_date="2026-09-03",
        instrument_key="NSE_INDEX|Nifty 50",
    )
    signal = view.selected
    assert signal is not None
    states = _states(signal)
    assert [states[n] for n in range(1, 10)] == [STATE_OK] * 9
    assert states[10] == STATE_FAIL
    assert all(states[n] == STATE_NOT_REACHED for n in range(11, 22))
    stopped = signal.stopped_at
    assert stopped is not None
    assert stopped.number == 10
    assert stopped.code == AdmissionCode.MIDPOINT_NOT_ALIGNED.value
    assert stopped.detail["reference_midpoint"] == 24000.0
    assert stopped.detail["index_close"] == 23960.0


def test_the_furthest_refusal_is_the_one_recorded() -> None:
    """Two refusals in one cycle: the ladder must show the deeper one.

    Recording the latest refusal instead would report a stale
    REFERENCE_NOT_READY and hide a sibling that cleared nine gates.
    """
    shallow = SimpleNamespace(
        event_type="CANDIDATE_ADMISSION",
        candidate_allowed=False,
        admission_code=AdmissionCode.CONTEXT_STALE.value,
    )
    deep = SimpleNamespace(
        event_type="CANDIDATE_ADMISSION",
        candidate_allowed=False,
        admission_code=AdmissionCode.MIDPOINT_NOT_ALIGNED.value,
    )
    assert _ranked_admission([deep, shallow]) is deep
    assert _ranked_admission([shallow, deep]) is deep
    admitted = SimpleNamespace(
        event_type="CANDIDATE_ADMISSION",
        candidate_allowed=True,
        admission_code=AdmissionCode.INITIAL_BULLISH_ALIGNMENT.value,
    )
    assert _ranked_admission([deep, admitted, shallow]) is admitted
    assert _ranked_admission([]) is None
    assert checkpoint_for_code(AdmissionCode.CONTEXT_STALE.value).number == 2

def _admitted_case(
    entry_type: str,
    code: str,
    *,
    events: list[dict] | None = None,
    gates: list[dict] | None = None,
    attempt_entry_type: str | None = None,
    decision_entry_type: str | None = None,
):
    attempt = {
        "signal_id": "sig-1",
        "run_id": "run-a",
        "trading_date": "2026-09-03",
        "direction": "BEARISH",
        "entry_type": entry_type if attempt_entry_type is None else attempt_entry_type,
        "governing_reference": "RED_BAR",
        "governing_midpoint": 24000.0,
        "cross_timestamp": "2026-09-03T11:30:00",
        "confirmation_timestamp": "2026-09-03T11:42:00",
        "risk_plan_code": "PRICED",
        "risk_plan_tradable": 1,
        "risk_stop_price": 24030.0,
        "risk_points": 30.0,
        "risk_stop_trigger": "CROSSING_5M_HIGH",
    }
    evidence = {
        "run-a": [
            _gate_row("candidate_scan", "OK", {"candidate_count": 1}, "2026-09-03T11:42:00"),
            *(gates or []),
            _decision_row(
                code=code,
                allowed=True,
                entry_type=(
                    entry_type if decision_entry_type is None else decision_entry_type
                ),
            ),
        ]
    }
    database = FakeLadderDatabase(
        attempts=[attempt],
        evidence=evidence,
        events={"sig-1": list(events or [])},
    )
    view = build_entry_ladder_view(
        database, trading_date="2026-09-03", instrument_key="NSE_INDEX|Nifty 50"
    )
    return view.selected


def test_a_bypassed_gate_is_not_a_failure() -> None:
    """The deputy path never runs VWAP or midpoint, and vice versa.

    Rendering a gate a path deliberately returns before as FAIL would report a
    refusal the strategy never made.
    """
    working = _admitted_case(
        "WORKING", AdmissionCode.WORKING_REFERENCE_CONFIRMED_FLAT.value
    )
    assert working is not None
    working_states = _states(working)
    assert working_states[8] == STATE_OK
    assert working_states[9] == STATE_NOT_APPLICABLE
    assert working_states[10] == STATE_NOT_APPLICABLE

    initial = _admitted_case("INITIAL", AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value)
    assert initial is not None
    initial_states = _states(initial)
    assert initial_states[8] == STATE_NOT_APPLICABLE
    assert initial_states[9] == STATE_OK
    assert initial_states[10] == STATE_OK
    assert initial_states[11] == STATE_OK
    assert initial_states[12] == STATE_OK
    assert STATE_FAIL not in initial_states.values()


def test_evidence_only_codes_never_block() -> None:
    """A demoted code is reported and cannot produce a FAIL.

    It is read out of one ``|``-separated token and split on commas *inside that
    token only* -- splitting the whole reason invents codes that were never
    recorded.
    """
    reason = (
        "NO_HARD_PERFORMANCE_BLOCKERS|OPPORTUNITY_HEALTH=0.42,0.61"
        "|SHADOW_ENTRY_WARNINGS=STRUCTURE_INVALID,BEARISH_EMA10_LOST"
    )
    assert parse_shadow_warnings(reason) == ("STRUCTURE_INVALID", "BEARISH_EMA10_LOST")
    assert parse_shadow_warnings(None) == ()
    assert parse_shadow_warnings("NO_TOKEN_HERE") == ()

    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        events=[
            {
                "state": "OPPORTUNITY_EVALUATED",
                "detail": reason,
                "timestamp": "2026-09-03T11:42:10",
            }
        ],
    )
    assert signal is not None
    codes = [note.code for note in signal.evidence_only]
    assert "STRUCTURE_INVALID" in codes
    assert "BEARISH_EMA10_LOST" in codes
    assert all(row.state != STATE_FAIL for row in signal.rows)
    assert _states(signal)[17] == STATE_OK


def test_admitted_signal_walks_the_whole_chain_to_open() -> None:
    """One assertion across all three stores."""
    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        events=[
            {"state": "OPPORTUNITY_EVALUATED", "detail": "OK", "timestamp": "2026-09-03T11:42:05"},
            {"state": "QUEUED", "detail": "committee", "timestamp": "2026-09-03T11:42:07"},
            {"state": "PORTFOLIO_APPROVED", "detail": "", "timestamp": "2026-09-03T11:42:08"},
            {"state": "EXECUTING", "detail": "", "timestamp": "2026-09-03T11:42:09"},
            {"state": "OPEN", "detail": "", "timestamp": "2026-09-03T11:42:11"},
        ],
    )
    assert signal is not None
    states = _states(signal)
    assert signal.stopped_at is None
    assert states[21] == STATE_OK
    assert all(states[n] == STATE_OK for n in range(13, 22))
    assert signal.risk_stop_price == 24030.0
    assert signal.risk_points == 30.0


def test_an_order_path_refusal_stops_the_ladder_there() -> None:
    """A stale candidate that expired before it could be traded."""
    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        events=[
            {"state": "OPPORTUNITY_EVALUATED", "detail": "OK", "timestamp": "2026-09-03T11:42:05"},
            {
                "state": "RED_BAR_V2_SIGNAL_EXPIRED",
                "detail": "age 512s",
                "timestamp": "2026-09-03T11:50:00",
            },
        ],
    )
    assert signal is not None
    states = _states(signal)
    assert states[14] == STATE_OK
    assert states[15] == STATE_FAIL
    assert all(states[n] == STATE_NOT_REACHED for n in (18, 19, 20, 21))
    stopped = signal.stopped_at
    assert stopped is not None and stopped.number == 15


def test_a_refusal_caps_how_far_the_candidate_is_said_to_have_reached() -> None:
    """The summary line may not contradict the stopper.

    The order path is a trail rather than a chain, so a candidate refused for
    staleness at 15 can still leave a committee row at 18. Reporting 18 as the
    reach would read as "stopped at 15, reached 18" in one breath.
    """
    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        events=[
            {"state": "OPPORTUNITY_EVALUATED", "detail": "OK", "timestamp": "2026-09-03T11:42:05"},
            {
                "state": "RED_BAR_V2_SIGNAL_EXPIRED",
                "detail": "age 512s",
                "timestamp": "2026-09-03T11:42:20",
            },
            {
                "state": "QUEUED",
                "detail": "committee",
                "timestamp": "2026-09-03T11:42:30",
            },
        ],
    )
    assert signal is not None
    states = _states(signal)
    assert states[15] == STATE_FAIL
    assert states[18] == STATE_OK, "the later answer stays on its own row"
    stopped = signal.stopped_at
    assert stopped is not None and stopped.number == 15
    assert signal.reached_number == 15


def test_a_recorded_refusal_outranks_a_derived_pass() -> None:
    """A gate row that says ERROR is not overruled by the chain.

    Rungs below the stopper are marked ok by derivation rather than by reading
    anything, so a rung whose own row recorded a refusal would otherwise be
    painted green by inference -- hiding a recorder bug behind the screen built
    to expose it.
    """
    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        gates=[
            _gate_row(
                "check:entry_window_open",
                "ERROR",
                {"reached": True, "candle_timestamp": "2026-09-03T15:04:00"},
                "2026-09-03T11:42:00",
            )
        ],
    )
    assert signal is not None
    states = _states(signal)
    assert states[3] == STATE_FAIL
    stopped = signal.stopped_at
    assert stopped is not None and stopped.number == 3
    assert stopped.code and "ENTRY_WINDOW_CLOSED" in stopped.code


def test_a_path_restricted_gate_is_not_failed_on_an_unknown_path() -> None:
    """An ERROR the path already explains may not become a refusal.

    The deployed build records ``check:vwap_aligned`` as ERROR on every WORKING
    admission because that path does not consult futures VWAP at all. Where the
    entry type survives, checkpoint 9 reads n/a and the question never arises;
    where it survives nowhere -- neither on the attempt nor in the decision
    artifact -- a genuine futures-VWAP refusal and a gate that simply sat the
    path out are indistinguishable, so inventing a refusal would libel a
    candidate the policy admitted.
    """
    signal = _admitted_case(
        "WORKING",
        AdmissionCode.WORKING_REFERENCE_CONFIRMED_FLAT.value,
        attempt_entry_type="",
        decision_entry_type="",
        gates=[
            _gate_row(
                "check:vwap_aligned",
                "ERROR",
                {"reached": True, "futures_vwap": None},
                "2026-09-03T11:42:00",
            )
        ],
    )
    assert signal is not None
    assert signal.entry_type is None, "the test needs the path to be unknowable"
    states = _states(signal)
    assert states[9] == STATE_OK
    assert signal.stopped_at is None


def test_the_committee_scoring_log_is_not_a_refusal() -> None:
    """DECISION_RECORDED is written per ranked contract, not as a verdict.

    Production writes one such row per candidate the committee scored, on
    signals that went on to open a position as readily as on ones it passed
    over. Reading it as a block put a FAIL on checkpoint 18 of a trade whose own
    checkpoint 21 said the position was open.
    """
    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        events=[
            {"state": "OPPORTUNITY_EVALUATED", "detail": "OK", "timestamp": "2026-09-03T11:42:05"},
            {
                "state": "DECISION_RECORDED",
                "detail": "candidate=NIFTY 23950 PE 08 SEP 26; rank=1;",
                "timestamp": "2026-09-03T11:42:06",
            },
            {"state": "QUEUED", "detail": "committee", "timestamp": "2026-09-03T11:42:07"},
            {"state": "PORTFOLIO_APPROVED", "detail": "", "timestamp": "2026-09-03T11:42:08"},
            {"state": "EXECUTING", "detail": "", "timestamp": "2026-09-03T11:42:09"},
            {"state": "OPEN", "detail": "", "timestamp": "2026-09-03T11:42:11"},
        ],
    )
    assert signal is not None
    states = _states(signal)
    assert states[18] == STATE_OK
    assert states[21] == STATE_OK
    assert signal.stopped_at is None


def test_exit_telemetry_cannot_push_the_entry_path_out_of_the_window() -> None:
    """A trade that stayed open must still show how it got open.

    An open position writes an ``EXIT_MONITOR`` row per candle, so a signal held
    any length of time has hundreds of them. Read newest-first with a per-signal
    cap, the states that opened the trade fall outside the window and the entry
    ladder reports NOT_REACHED on rungs the trade plainly cleared -- worst on the
    candidates that succeeded, which are the ones worth reading.
    """
    opening = [
        {"state": "CANDIDATE_SELECTION", "detail": "", "timestamp": "2026-09-03T11:42:01"},
        {"state": "OPPORTUNITY_EVALUATED", "detail": "OK", "timestamp": "2026-09-03T11:42:05"},
        {"state": "QUEUED", "detail": "committee", "timestamp": "2026-09-03T11:42:07"},
        {"state": "PORTFOLIO_APPROVED", "detail": "", "timestamp": "2026-09-03T11:42:08"},
        {"state": "EXECUTING", "detail": "", "timestamp": "2026-09-03T11:42:09"},
        {"state": "OPEN", "detail": "", "timestamp": "2026-09-03T11:42:11"},
    ]
    monitoring = [
        {
            "state": "EXIT_MONITOR",
            "detail": "holding",
            "timestamp": "2026-09-03T%02d:%02d:00" % (12 + minute // 60, minute % 60),
        }
        for minute in range(120)
    ]
    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        events=opening + monitoring,
    )
    assert signal is not None
    states = _states(signal)
    assert states[21] == STATE_OK
    assert all(states[n] == STATE_OK for n in range(13, 22))
    assert signal.stopped_at is None
    assert signal.reached_number == 21


def test_a_late_refusal_is_not_lost_behind_thousands_of_earlier_rows() -> None:
    """The committee's refusal is written last, and must still be read.

    A signal the committee keeps re-ranking logs a DECISION_RECORDED row per
    contract per cycle all day, and is only marked SKIPPED_OPPORTUNITY in the
    end-of-session sweep. One real signal ran to 234 rows across eighteen states
    this way. Any cap counted per signal loses the tail, and the tail is the one
    row that answers the screen's question.
    """
    noise = [
        {
            "state": "DECISION_RECORDED",
            "detail": "candidate=NIFTY 23950 PE 08 SEP 26; rank=1;",
            "timestamp": "2026-09-03T%02d:%02d:%02d" % (
                13 + row // 3600, (row // 60) % 60, row % 60
            ),
        }
        for row in range(2000)
    ]
    signal = _admitted_case(
        "INITIAL",
        AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
        events=[
            {"state": "OPPORTUNITY_EVALUATED", "detail": "OK", "timestamp": "2026-09-03T11:42:05"},
            *noise,
            {
                "state": "SKIPPED_OPPORTUNITY",
                "detail": "No candidate cleared the guarded opportunity",
                "timestamp": "2026-09-03T22:43:15",
            },
        ],
    )
    assert signal is not None
    states = _states(signal)
    assert states[14] == STATE_OK
    assert states[18] == STATE_FAIL
    stopped = signal.stopped_at
    assert stopped is not None and stopped.number == 18
    assert stopped.code == "SKIPPED_OPPORTUNITY"
    read = [str(event["state"]) for event in signal.state_events]
    assert read.count("DECISION_RECORDED") <= 10, "the noise must stay bounded"


def test_context_states_are_read_but_decide_nothing() -> None:
    """The narrowed read must not smuggle a verdict in with the context.

    The states read purely so a reader can see what the committee ranked have to
    stay inert. If one of them were also a pass state or a blocking code, the
    read would look like context and behave like a gate -- which is how
    DECISION_RECORDED came to put a FAIL on checkpoint 18 of a trade that opened.
    """
    wanted = set(order_path_event_states())
    for state in CONTEXT_EVENT_STATES:
        assert state in wanted, state
    for checkpoint in order_path_checkpoints():
        answering = set(checkpoint.pass_states) | set(checkpoint.blocking_codes)
        overlap = answering & set(CONTEXT_EVENT_STATES)
        assert not overlap, f"checkpoint {checkpoint.number} keys off {overlap}"


def test_the_join_survives_a_missing_half() -> None:
    """Neither half of the join may fabricate the other."""
    orphan_attempt = {
        "signal_id": "sig-orphan",
        "run_id": "run-gone",
        "trading_date": "2026-09-03",
        "direction": "BULLISH",
        "entry_type": "INITIAL",
        "cross_timestamp": "2026-09-03T10:00:00",
        "confirmation_timestamp": "2026-09-03T10:01:00",
    }
    view = build_entry_ladder_view(
        FakeLadderDatabase(attempts=[orphan_attempt]),
        trading_date="2026-09-03",
        instrument_key="NSE_INDEX|Nifty 50",
    )
    signal = view.selected
    assert signal is not None
    assert len(signal.rows) == len(ENTRY_LADDER)
    # An INITIAL attempt still marks the deputy gate as off its path, so the
    # claim is the sharper one: nothing was answered, and nothing was invented.
    assert all(
        row.state in (STATE_NOT_REACHED, STATE_NOT_APPLICABLE) for row in signal.rows
    )
    assert _states(signal)[8] == STATE_NOT_APPLICABLE
    assert signal.stopped_at is None
    assert signal.reached_number == 0


def test_a_date_with_nothing_recorded_renders_no_signals() -> None:
    view = build_entry_ladder_view(
        FakeLadderDatabase(),
        trading_date="2026-09-05",
        instrument_key="NSE_INDEX|Nifty 50",
    )
    assert view.signals == ()
    assert view.selected is None
    assert view.cycle["trading_date"] == "2026-09-05"

def test_the_assembler_bounds_how_much_evidence_it_reads() -> None:
    """A date with hundreds of cycles must not turn one page load into a scan."""
    evidence = {
        f"run-{index}": [
            _decision_row(
                code=AdmissionCode.CONTEXT_STALE.value,
                allowed=False,
                at=f"2026-09-03T1{index}:00:00",
            )
        ]
        for index in range(5)
    }
    database = FakeLadderDatabase(evidence=evidence)
    build_entry_ladder_view(
        database,
        trading_date="2026-09-03",
        instrument_key="NSE_INDEX|Nifty 50",
        max_runs=2,
    )
    assert len(database.evidence_reads) == 2


def test_evidence_run_ids_scope_to_one_date_against_a_real_database(tmp_path) -> None:
    """The one piece of new storage code, against real SQL.

    Every other ``process_evidence`` reader is keyed by run_id or is global, so
    finding the cycles for a chosen date needed a new read.
    """
    database = RedBarDatabase(tmp_path / "ladder.db")
    database.initialize()
    for run_id, started_at in (
        ("run-old", "2026-09-02T11:00:00"),
        ("run-new", "2026-09-03T11:00:00"),
    ):
        database.write_step_evidence(
            process_name="red_bar_v2_strategy",
            run_id=run_id,
            step_name="admission_decision",
            parent_step="strategy_evaluate",
            started_at=started_at,
            status="ERROR",
            artifacts={
                "admission_code": AdmissionCode.MIDPOINT_NOT_ALIGNED.value,
                "candidate_allowed": False,
                "conditions": {"midpoint_aligned": False, "index_close": 23960.0},
            },
        )
    scoped = database.read_evidence_run_ids(
        process_name="red_bar_v2_strategy",
        step_name="admission_decision",
        date_prefix="2026-09-03",
    )
    assert [row["run_id"] for row in scoped] == ["run-new"]
    everything = database.read_evidence_run_ids(
        process_name="red_bar_v2_strategy", step_name="admission_decision"
    )
    assert [row["run_id"] for row in everything] == ["run-new", "run-old"]
    assert (
        database.read_evidence_run_ids(
            process_name="red_bar_v2_strategy", step_name="check:never_written"
        )
        == []
    )

    view = build_entry_ladder_view(
        database,
        trading_date="2026-09-03",
        instrument_key="NSE_INDEX|Nifty 50",
    )
    signal = view.selected
    assert signal is not None
    assert signal.run_id == "run-new"
    stopped = signal.stopped_at
    assert stopped is not None and stopped.number == 10
    assert stopped.detail["index_close"] == 23960.0


def _insert_admitted_attempt(
    database: RedBarDatabase,
    *,
    run_id: str,
    signal_id: str = "RBV2-LADDERJOIN0000000001",
    confirmation: str = "2026-09-03T11:31:00+05:30",
    direction: str = "BEARISH",
) -> str:
    """One published V2 attempt, written the way the paper bridge writes it.

    A direct insert rather than a call into the bridge: the bridge's own
    freshness window is clock-dependent and separately tested, and what this
    test is about is the join, not the publish.
    """
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            INSERT INTO signal_attempts(
                signal_id,run_id,instrument_key,trading_date,
                level_type,level_value,direction,state,
                cross_timestamp,confirmation_timestamp,underlying_entry,
                entry_type,governing_reference,governing_midpoint,
                risk_plan_tradable,risk_plan_code,
                risk_stop_price,risk_points,risk_stop_trigger,
                confirmation_delay_minutes,created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                run_id,
                "NSE_INDEX|Nifty 50",
                "2026-09-03",
                "RED_BAR_V2_MIDPOINT",
                24000.0,
                direction,
                "ACTIVE",
                "2026-09-03T11:30:00+05:30",
                confirmation,
                23960.0,
                "INITIAL",
                "RED_BAR",
                24000.0,
                1,
                "RISK_PLAN_OK",
                23995.0,
                35.0,
                "FIVE_MINUTE_CROSSING_HIGH",
                1,
                confirmation,
            ),
        )
        conn.commit()
    return signal_id


def test_the_three_table_join_holds_against_real_storage(tmp_path) -> None:
    """The whole chain through real SQL, not a fake database.

    ``process_evidence.run_id`` -> ``signal_attempts.run_id``/``signal_id`` ->
    ``execution_state_events.signal_id``. Every other join test drives a fake, so
    this is the one that would catch a column that does not survive a real
    round-trip.
    """
    database = RedBarDatabase(tmp_path / "ladder-join.db")
    database.initialize()
    run_id = "cycle-2026-09-03-114"
    signal_id = _insert_admitted_attempt(database, run_id=run_id)

    # Checkpoint numbers are the catalog's, so 8 -- the deputy's gate, which an
    # INITIAL entry never consults -- is absent rather than renumbered.
    gates = (
        ("check:reference_ready", 1),
        ("check:context_fresh", 2),
        ("check:entry_window_open", 3),
        ("check:duplicate_signal", 4),
        ("check:reversal_already_consumed", 5),
        ("check:active_trade", 6),
        ("check:previous_trade_closed", 7),
        ("check:vwap_aligned", 9),
        ("check:midpoint_aligned", 10),
    )
    for index, (step, checkpoint) in enumerate(gates):
        database.write_step_evidence(
            process_name="red_bar_v2_strategy",
            run_id=run_id,
            step_name=step,
            parent_step="strategy_evaluate",
            started_at=f"2026-09-03T06:01:{index:02d}",
            status="OK",
            artifacts={
                "checkpoint": checkpoint,
                "reached": True,
                "candidate_allowed": True,
            },
        )
    database.write_step_evidence(
        process_name="red_bar_v2_strategy",
        run_id=run_id,
        step_name="admission_decision",
        parent_step="strategy_evaluate",
        started_at="2026-09-03T06:01:30",
        status="OK",
        artifacts={
            "admission_code": AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value,
            "candidate_allowed": True,
            "entry_type": "INITIAL",
            "direction": "BEARISH",
            "option_side": "PE",
            # The attempt's own cross timestamp: this is what the assembler
            # matches on when one run holds more than one admission.
            "reference_timestamp": "2026-09-03T11:30:00+05:30",
            "conditions": {"midpoint_aligned": True, "vwap_aligned": True},
        },
    )
    for offset, state in enumerate(
        (
            "OPPORTUNITY_EVALUATED",
            "CANDIDATE_SELECTION",
            "QUEUED",
            "DECISION_RECORDED",
            "PORTFOLIO_APPROVED",
            "EXECUTING",
            "OPEN",
        )
    ):
        database.insert_execution_state_event(
            {
                "event_id": f"{signal_id}-{offset}",
                "signal_id": signal_id,
                "order_id": "PAPER-1",
                "state": state,
                "detail": "NO_HARD_PERFORMANCE_BLOCKERS",
                "candidate_score": 0.62,
                "timestamp": f"2026-09-03T11:3{offset + 1}:00+05:30",
            }
        )

    view = build_entry_ladder_view(
        database, trading_date="2026-09-03", instrument_key="NSE_INDEX|Nifty 50"
    )
    signal = view.selected
    assert signal is not None
    assert (signal.signal_id, signal.run_id) == (signal_id, run_id)
    assert signal.entry_type == "INITIAL"
    assert signal.governing_reference == "RED_BAR"
    assert (signal.risk_stop_price, signal.risk_points) == (23995.0, 35.0)

    states = _states(signal)
    # Checkpoint 8 is the deputy's own gate and an INITIAL entry never consults it.
    assert states[8] == STATE_NOT_APPLICABLE
    assert [number for number, state in states.items() if state != STATE_OK] == [8]
    assert signal.stopped_at is None
    assert signal.reached_number == 21
    # Narrowed to the states the ladder reads, in the order they happened.
    assert [str(event["state"]) for event in signal.state_events] == [
        "OPPORTUNITY_EVALUATED",
        "CANDIDATE_SELECTION",
        "QUEUED",
        "DECISION_RECORDED",
        "PORTFOLIO_APPROVED",
        "EXECUTING",
        "OPEN",
    ]
    assert len(signal.evidence_rows) == 10


def _write_cycle(
    database: RedBarDatabase,
    *,
    run_id: str,
    candle: str,
    direction: str,
    started_at: str,
    entry_type: str = "INITIAL",
) -> None:
    """One strategy cycle, recorded the way the deployed monitor records it.

    The cycle stamps the completed candle it judged and an admission decision
    with no reference timestamp, because that is what production writes.
    """
    database.write_step_evidence(
        process_name="red_bar_v2_strategy",
        run_id=run_id,
        step_name="latest_completed_1m_candle",
        parent_step="strategy_evaluate",
        started_at=started_at,
        status="OK",
        artifacts={"candle_timestamp": candle, "candle_close": 23960.0},
    )
    for step in (
        "check:reference_ready",
        "check:context_fresh",
        "check:entry_window_open",
        "check:duplicate_signal",
        "check:reversal_already_consumed",
        "check:active_trade",
        "check:previous_trade_closed",
        "check:vwap_aligned",
        "check:midpoint_aligned",
    ):
        database.write_step_evidence(
            process_name="red_bar_v2_strategy",
            run_id=run_id,
            step_name=step,
            parent_step="strategy_evaluate",
            started_at=started_at,
            status="OK",
            artifacts={"reached": True, "candidate_allowed": True},
        )
    database.write_step_evidence(
        process_name="red_bar_v2_strategy",
        run_id=run_id,
        step_name="admission_decision",
        parent_step="strategy_evaluate",
        started_at=started_at,
        status="OK",
        artifacts={
            "admission_code": (
                AdmissionCode.INITIAL_BEARISH_ALIGNMENT.value
                if direction == "BEARISH"
                else AdmissionCode.INITIAL_BULLISH_ALIGNMENT.value
            ),
            "candidate_allowed": True,
            "entry_type": entry_type,
            "direction": direction,
            "option_side": "PE" if direction == "BEARISH" else "CE",
        },
    )


def test_an_attempt_finds_its_cycle_when_the_two_stores_disagree_on_run_id(
    tmp_path,
) -> None:
    """The join production actually needs, and the one a shared run_id hides.

    Every ``signal_attempts`` row is minted under an ``RBV2-*`` run id by the
    paper bridge; every ``red_bar_v2_strategy`` evidence row is written under the
    monitor loop's own ``paper-monitor-*`` id. The two namespaces never intersect,
    so keying gate rows off the attempt's run id alone leaves the admission half
    of every published signal reading "not reached" -- which is what the deployed
    database showed. The candle the cycle judged is the field both stores carry.
    """
    database = RedBarDatabase(tmp_path / "ladder-namespaces.db")
    database.initialize()
    signal_id = _insert_admitted_attempt(
        database, run_id="RBV2-PAPER-RUNTIME-9c1f2a", signal_id="RBV2-NAMESPACE00000000001"
    )
    # An earlier cycle on a different candle, and one on the right candle that
    # admitted the other side of the book. Neither may be attached.
    _write_cycle(
        database,
        run_id="paper-monitor-2026-09-03T05:55:02-aaaaaa",
        candle="2026-09-03T11:25:00+05:30",
        direction="BEARISH",
        started_at="2026-09-03T05:55:03",
    )
    _write_cycle(
        database,
        run_id="paper-monitor-2026-09-03T06:01:02-bbbbbb",
        candle="2026-09-03T11:31:00+05:30",
        direction="BULLISH",
        started_at="2026-09-03T06:01:03",
    )
    _write_cycle(
        database,
        run_id="paper-monitor-2026-09-03T06:01:40-cccccc",
        candle="2026-09-03T11:31:00+05:30",
        direction="BEARISH",
        started_at="2026-09-03T06:01:41",
    )
    for offset, state in enumerate(("OPPORTUNITY_EVALUATED", "CANDIDATE_SELECTION")):
        database.insert_execution_state_event(
            {
                "event_id": f"{signal_id}-{offset}",
                "signal_id": signal_id,
                "order_id": None,
                "state": state,
                "detail": "NO_HARD_PERFORMANCE_BLOCKERS",
                "candidate_score": 0.5,
                "timestamp": f"2026-09-03T11:3{offset + 2}:00+05:30",
            }
        )

    view = build_entry_ladder_view(
        database, trading_date="2026-09-03", instrument_key="NSE_INDEX|Nifty 50"
    )
    published = [item for item in view.signals if item.signal_id == signal_id]
    assert len(published) == 1
    signal = published[0]
    # The attempt keeps its own run id; the cycle it was matched to is named
    # separately, so the reader can go and look at that cycle's rows.
    assert signal.run_id == "RBV2-PAPER-RUNTIME-9c1f2a"
    assert signal.evidence_run_id == "paper-monitor-2026-09-03T06:01:40-cccccc"

    states = _states(signal)
    # The admission half is answered from the matched cycle rather than blank.
    assert [number for number in range(1, 8) if states[number] != STATE_OK] == []
    assert states[10] == STATE_OK
    assert signal.stopped_at is None
    assert signal.reached_number >= 17

    # The cycle that was claimed does not also appear as an unpublished refusal,
    # and the two cycles that did not match still stand on their own.
    labelled = {item.evidence_run_id for item in view.signals}
    assert "paper-monitor-2026-09-03T05:55:02-aaaaaa" in labelled
    assert "paper-monitor-2026-09-03T06:01:02-bbbbbb" in labelled
    assert sum(
        1
        for item in view.signals
        if item.evidence_run_id == "paper-monitor-2026-09-03T06:01:40-cccccc"
    ) == 1


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubStreamlit(_Ctx):
    """Enough of streamlit to prove the page assembles its own text."""

    def __init__(self, today) -> None:
        self.today = today
        self.calls: list[tuple] = []
        self.text: list[str] = []

    def _record(self, kind, value):
        self.calls.append((kind, str(value)))
        self.text.append(str(value))

    def title(self, text, **kwargs):
        self._record("title", text)

    def info(self, text, **kwargs):
        self._record("info", text)

    def warning(self, text, **kwargs):
        self._record("warning", text)

    def success(self, text, **kwargs):
        self._record("success", text)

    def caption(self, text, **kwargs):
        self._record("caption", text)

    def markdown(self, text, **kwargs):
        self._record("markdown", text)

    def metric(self, label, value, **kwargs):
        self._record("metric", f"{label}={value}")

    def dataframe(self, data, **kwargs):
        self.calls.append(("dataframe", str(len(list(data)))))

    def columns(self, spec, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_Ctx() for _ in range(count)]

    def expander(self, label, **kwargs):
        return _Ctx()

    def date_input(self, label, value=None, **kwargs):
        return self.today

    def number_input(self, label, low, high, default, step, **kwargs):
        return default

    def selectbox(self, label, options, index=0, **kwargs):
        return list(options)[index]


def _render(database, today, monkeypatch) -> _StubStreamlit:
    from red_bar_lab.ui.pages import v2_entry_ladder as page

    stub = _StubStreamlit(today)
    monkeypatch.setattr(page, "st", stub)
    page.render_page(
        None, None, database, "", "NIFTY 50", "NSE_INDEX|Nifty 50", 1
    )
    return stub


def test_the_page_is_registered_for_navigation() -> None:
    import red_bar_lab.ui.workspace as workspace

    assert workspace._PAGE_MODULE_PATHS["V2 Entry Ladder"] == (
        "red_bar_lab.ui.pages.v2_entry_ladder"
    )


def test_the_page_names_the_checkpoint_that_stopped_the_trade(monkeypatch) -> None:
    from datetime import date

    evidence = {
        "run-a": [
            _gate_row("candidate_scan", "OK", {"candidate_count": 1}, "2026-09-03T11:42:00"),
            _decision_row(
                code=AdmissionCode.MIDPOINT_NOT_ALIGNED.value,
                allowed=False,
                conditions={"midpoint_aligned": False, "index_close": 23960.0},
            ),
            _gate_row(
                "check:rsi_informational",
                "ERROR",
                {"rsi": 41.2},
                "2026-09-03T11:42:00",
            ),
        ]
    }
    stub = _render(
        FakeLadderDatabase(evidence=evidence), date(2026, 9, 3), monkeypatch
    )
    blob = "\n".join(stub.text)
    assert "OBSERVATIONAL ONLY" in blob
    assert "Stopped at checkpoint 10" in blob
    assert f"FAIL {AdmissionCode.MIDPOINT_NOT_ALIGNED.value}" in blob
    assert "EVIDENCE ONLY" in blob
    assert "RSI_INFORMATIONAL" in blob
    assert "21 · Position open" in blob


def test_the_page_renders_a_day_with_no_data(monkeypatch) -> None:
    from datetime import date

    stub = _render(FakeLadderDatabase(), date(2026, 9, 5), monkeypatch)
    blob = "\n".join(stub.text)
    assert "No Red Bar V2 candidate was recorded for 2026-09-05" in blob

