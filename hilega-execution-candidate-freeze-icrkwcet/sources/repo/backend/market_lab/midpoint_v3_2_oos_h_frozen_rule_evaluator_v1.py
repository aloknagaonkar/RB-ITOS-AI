from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from market_lab.midpoint_v3_2_oos_h_freeze_contract_v1 import (
    CONTRACT_RULE,
    ENTRY_RULE,
    EXIT_POLICY_ID,
    load_json,
    verify_contract_files,
)

import market_lab.midpoint_break_strength_failure_v2 as strength
import market_lab.midpoint_failure_diagnostics_v2_2 as diagnostics
import market_lab.midpoint_stable_feature_state_machine_v3_2 as state
import market_lab.midpoint_v3_2_exact_option_economics_v1 as economics

RESEARCH_VERSION = "MIDPOINT_V3_2_OOS_H_FROZEN_RULE_EVALUATOR_V1"
EXPECTED_BLOCK = "OOS_H"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "unavailable"}:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@contextmanager
def _temporary_allowed_blocks(module: Any, allowed: set[str]):
    old = getattr(module, "ALLOWED_BLOCKS", None)
    setattr(module, "ALLOWED_BLOCKS", set(allowed))
    try:
        yield
    finally:
        if old is not None:
            setattr(module, "ALLOWED_BLOCKS", old)


def validate_frozen_inputs(
    *,
    contract: dict[str, Any],
    frozen_state: dict[str, Any],
    framework: dict[str, Any],
) -> None:
    mismatches = verify_contract_files(contract)
    if mismatches:
        raise ValueError("freeze contract file mismatch: " + "; ".join(mismatches))

    if contract.get("status") != "FROZEN":
        raise ValueError("freeze contract is not FROZEN")
    if contract.get("entry_version") != EXPECTED_STATE_VERSION:
        raise ValueError("freeze contract entry version mismatch")
    if contract.get("entry_rule") != ENTRY_RULE:
        raise ValueError("freeze contract entry rule mismatch")
    if contract.get("contract_rule") != CONTRACT_RULE:
        raise ValueError("freeze contract contract rule mismatch")
    if contract.get("exit_policy_id") != EXIT_POLICY_ID:
        raise ValueError("freeze contract exit policy mismatch")

    if frozen_state.get("status") != "AVAILABLE":
        raise ValueError("frozen development state artifact is not AVAILABLE")
    if frozen_state.get("research_version") != EXPECTED_STATE_VERSION:
        raise ValueError("unexpected frozen development state version")

    rules = frozen_state.get("t3_train_only_rules")
    if not isinstance(rules, dict) or not rules:
        raise ValueError("frozen development state has no t3_train_only_rules")

    guard = frozen_state.get("leakage_guard") or {}
    expected_guard = {
        "thresholds_derived_from_train_only": True,
        "feature_activation_derived_from_train_only": True,
        "oos_h_used": False,
        "pnl_used_for_rule_selection": False,
    }
    for key, expected in expected_guard.items():
        if guard.get(key) != expected:
            raise ValueError(
                f"frozen state leakage guard {key} expected {expected!r}, "
                f"got {guard.get(key)!r}"
            )

    if framework.get("status") != "AVAILABLE":
        raise ValueError("OOS-H framework is not AVAILABLE")
    if framework.get("research_version") != "OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1":
        raise ValueError("unexpected OOS-H framework version")


def build_holdout_checkpoint_rows(
    framework: dict[str, Any],
    *,
    strength_module: Any = strength,
) -> list[dict[str, Any]]:
    """Build structural/OI checkpoint rows without consulting future outcome labels.

    The development helper build_rows() is intentionally not called because it
    filters events using future CONTINUATION/REVERSAL labels.  For the pristine
    holdout we use only structure, checkpoint snapshots, price features and OI.
    """
    rows: list[dict[str, Any]] = []

    for event in framework.get("events", []):
        if str(event.get("block")) != EXPECTED_BLOCK:
            continue

        direction = strength_module.direction_for_event(event)
        if direction is None:
            continue

        for checkpoint in strength_module.CHECKPOINTS:
            snapshot = strength_module.snapshot_at(event, checkpoint)
            if snapshot is None:
                continue

            ce = strength_module.oi_state(snapshot, "CE")
            pe = strength_module.oi_state(snapshot, "PE")
            oi = strength_module.classify_oi_pair(direction, ce, pe)
            oi.update(
                {
                    "ce_state": ce,
                    "pe_state": pe,
                    "ce_premium_change_5m_pct": strength_module.first_num(
                        snapshot,
                        ("ce_5m_premium_change_pct", "ce_premium_change_5m_pct"),
                    ),
                    "ce_oi_change_5m_pct": strength_module.first_num(
                        snapshot,
                        ("ce_5m_oi_change_pct", "ce_oi_change_5m_pct"),
                    ),
                    "pe_premium_change_5m_pct": strength_module.first_num(
                        snapshot,
                        ("pe_5m_premium_change_pct", "pe_premium_change_5m_pct"),
                    ),
                    "pe_oi_change_5m_pct": strength_module.first_num(
                        snapshot,
                        ("pe_5m_oi_change_pct", "pe_oi_change_5m_pct"),
                    ),
                }
            )

            rows.append(
                {
                    "block": EXPECTED_BLOCK,
                    "session_date": event.get("session_date"),
                    "setup_type": event.get("setup_type"),
                    "direction": direction,
                    # Explicitly stripped: these fields must not drive H selection.
                    "primary_outcome": None,
                    "outcome_label": None,
                    "checkpoint_minutes": checkpoint,
                    "checkpoint_label": (
                        "T0" if checkpoint == 0 else f"T+{checkpoint}"
                    ),
                    "timestamp": snapshot.get("timestamp"),
                    "price_features": strength_module.extract_features(
                        snapshot, direction
                    ),
                    "oi": oi,
                }
            )

    return rows


def prepare_holdout_rows(
    rows: list[dict[str, Any]],
    *,
    diagnostics_module: Any = diagnostics,
) -> list[dict[str, Any]]:
    # prepare_rows() only needs a runtime block-scope override. It computes
    # corrected momentum, checkpoint giveback and exact T1->T3 OI transition.
    with _temporary_allowed_blocks(diagnostics_module, {EXPECTED_BLOCK}):
        prepared = diagnostics_module.prepare_rows(rows)

    for row in prepared:
        if row.get("block") != EXPECTED_BLOCK:
            raise ValueError("non-OOS_H row escaped holdout preparation")
        if row.get("primary_outcome") is not None or row.get("outcome_label") is not None:
            raise ValueError("future outcome leaked into prepared holdout row")

    return prepared


def build_holdout_events(
    rows: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    diagnostics_module: Any = diagnostics,
    state_module: Any = state,
) -> list[dict[str, Any]]:
    """Apply frozen V3.2 rules without the development outcome-label filter."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        if row.get("checkpoint_minutes") in {1, 3}:
            groups[diagnostics_module.event_key(row)].append(row)

    events: list[dict[str, Any]] = []
    for group in groups.values():
        by_cp = {int(row["checkpoint_minutes"]): row for row in group}
        if 1 not in by_cp or 3 not in by_cp:
            continue

        t1 = by_cp[1]
        t3 = by_cp[3]

        t1_obs = state_module.observe_t1(t1)
        t3_score = state_module.score_t3(t3, rules)
        t3_state = state_module.classify_t3(t3, t3_score)

        events.append(
            {
                "block": EXPECTED_BLOCK,
                "session_date": t3.get("session_date"),
                "setup_type": t3.get("setup_type"),
                "direction": t3.get("direction"),
                "primary_outcome": None,
                "outcome_label": None,
                "t1_observation_state": t1_obs["state"],
                "t1_observation": t1_obs,
                "t3_state": t3_state,
                "t3_score": t3_score,
                "t3_timestamp": t3.get("timestamp"),
                "exact_oi_transition_t1_to_t3": t3.get(
                    "exact_oi_transition_t1_to_t3"
                ),
            }
        )

    return events


def _minute_iso(value: str, economics_module: Any = economics) -> str:
    if hasattr(economics_module, "parse_dt"):
        return economics_module.parse_dt(value).replace(
            second=0, microsecond=0
        ).isoformat()
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).replace(second=0, microsecond=0).isoformat()


def _fallback_positioning_atm_index(
    rows: Sequence[dict[str, str]],
    *,
    economics_module: Any = economics,
) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        offset = _finite(row.get("strike_offset"))
        if offset is None or abs(offset) > 1e-9:
            continue
        key = (row["session_date"], _minute_iso(row["timestamp"], economics_module))
        if key in out:
            raise ValueError(f"duplicate exact ATM positioning row: {key}")
        out[key] = row
    return out


def _fallback_ohlc_index(
    rows: Sequence[dict[str, str]],
    *,
    economics_module: Any = economics,
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)

    for raw in rows:
        row = dict(raw)
        date = str(row.get("session_date") or "")
        instrument = str(row.get("instrument_key") or "").strip()
        timestamp = str(row.get("timestamp") or "").strip()
        if not date or not instrument or not timestamp:
            continue

        for field in ("open", "high", "low", "close"):
            row[field] = _finite(row.get(field))

        minute = _minute_iso(timestamp, economics_module)
        key = (date, instrument)
        if minute in out[key]:
            raise ValueError(f"duplicate option OHLC minute: {key} {minute}")
        out[key][minute] = row

    return dict(out)


def build_economics_indexes(
    *,
    positioning_path: Path,
    ohlc_path: Path,
    economics_module: Any = economics,
):
    loader = getattr(economics_module, "load_csv", _load_csv)
    pos_rows = loader(positioning_path)
    ohlc_rows = loader(ohlc_path)

    if hasattr(economics_module, "positioning_atm_index"):
        pos_idx = economics_module.positioning_atm_index(pos_rows)
    elif hasattr(economics_module, "positioning_index"):
        # Use only if the frozen module's build_trade/exact_atm_contract expects it.
        # In current V1 the exact economics path normally exposes an ATM index.
        candidate = economics_module.positioning_index(pos_rows)
        # positioning_index in some modules uses a 3-part key and is not suitable.
        sample_key = next(iter(candidate), ())
        pos_idx = (
            candidate
            if isinstance(sample_key, tuple) and len(sample_key) == 2
            else _fallback_positioning_atm_index(
                pos_rows, economics_module=economics_module
            )
        )
    else:
        pos_idx = _fallback_positioning_atm_index(
            pos_rows, economics_module=economics_module
        )

    for name in ("option_ohlc_index", "ohlc_index"):
        fn = getattr(economics_module, name, None)
        if callable(fn):
            try:
                ohlc_idx = fn(ohlc_rows)
                break
            except TypeError:
                continue
    else:
        ohlc_idx = _fallback_ohlc_index(
            ohlc_rows, economics_module=economics_module
        )

    return pos_idx, ohlc_idx


def evaluate(
    *,
    contract: dict[str, Any],
    frozen_state: dict[str, Any],
    framework: dict[str, Any],
    positioning_path: Path,
    ohlc_path: Path,
) -> dict[str, Any]:
    validate_frozen_inputs(
        contract=contract,
        frozen_state=frozen_state,
        framework=framework,
    )

    checkpoint_rows = build_holdout_checkpoint_rows(framework)
    prepared_rows = prepare_holdout_rows(checkpoint_rows)
    rules = frozen_state["t3_train_only_rules"]
    events = build_holdout_events(prepared_rows, rules)

    confirmed = [
        event for event in events
        if event.get("t3_state") == "CONFIRM_CONTINUATION"
    ]

    pos_idx, ohlc_idx = build_economics_indexes(
        positioning_path=positioning_path,
        ohlc_path=ohlc_path,
    )

    trades: list[dict[str, Any]] = []
    for event in confirmed:
        raw_t3 = event.get("t3_timestamp")
        if not raw_t3:
            raise ValueError(
                f"confirmed H event missing T3 timestamp: "
                f"{event.get('session_date')} {event.get('direction')}"
            )
        t3 = economics.parse_dt(str(raw_t3))
        trade = economics.build_trade(event, t3, pos_idx, ohlc_idx)
        # The frozen build_trade currently writes retrospective outcome metadata.
        # H evaluation strips it so no future label survives into the final replay.
        trade["primary_outcome"] = None
        trade["outcome_family"] = None
        trades.append(trade)

    state_counts = Counter(str(event.get("t3_state")) for event in events)
    direction_counts = Counter(
        str(event.get("direction")) for event in confirmed
    )

    instrument_available = sum(bool(x.get("instrument_available")) for x in trades)
    entry_available = sum(bool(x.get("entry_available")) for x in trades)
    complete = sum(bool(x.get("complete_15m_path")) for x in trades)

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "block": EXPECTED_BLOCK,
        "entry_version": EXPECTED_STATE_VERSION,
        "entry_rule": ENTRY_RULE,
        "contract_rule": CONTRACT_RULE,
        "frozen_policy_id": EXIT_POLICY_ID,
        "source_framework_version": framework.get("research_version"),
        "frozen_rules_source": "t3_train_only_rules",
        "checkpoint_row_count": len(checkpoint_rows),
        "prepared_checkpoint_row_count": len(prepared_rows),
        "structural_event_count": len(events),
        "t3_state_counts": dict(state_counts),
        "confirmed_candidate_count": len(confirmed),
        "confirmed_direction_counts": dict(direction_counts),
        "instrument_available_count": instrument_available,
        "entry_available_count": entry_available,
        "complete_15m_path_count": complete,
        "rows": trades,
        "integrity": {
            "freeze_hashes_verified": True,
            "frozen_train_rules_loaded_not_rederived": True,
            "future_outcome_used_for_candidate_selection": False,
            "future_outcome_retained_in_trade_rows": False,
            "development_build_events_used": False,
            "exact_frozen_build_trade_used": True,
            "oos_h_only": True,
        },
        "governance": {
            "threshold_search_performed": False,
            "feature_activation_search_performed": False,
            "alternative_entry_rule_search_performed": False,
            "alternative_exit_search_performed": False,
            "paper_or_live_order_emission_allowed": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Apply frozen Midpoint V3.2 TRAIN-derived rules to pristine OOS-H "
            "without future-outcome selection or threshold re-derivation."
        )
    )
    parser.add_argument("--freeze-contract", required=True)
    parser.add_argument("--frozen-state", required=True)
    parser.add_argument("--framework", required=True)
    parser.add_argument("--positioning", required=True)
    parser.add_argument("--ohlc", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = evaluate(
        contract=load_json(Path(args.freeze_contract)),
        frozen_state=load_json(Path(args.frozen_state)),
        framework=load_json(Path(args.framework)),
        positioning_path=Path(args.positioning),
        ohlc_path=Path(args.ohlc),
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
