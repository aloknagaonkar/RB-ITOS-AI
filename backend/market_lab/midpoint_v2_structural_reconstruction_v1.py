from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from market_lab import midpoint_break_strength_failure_v2 as strength
from market_lab import midpoint_failure_diagnostics_v2_2 as diagnostics
from market_lab import midpoint_stable_feature_state_machine_v3_2 as state
from market_lab.midpoint_v2_research_foundation_v1 import (
    ALLOWED_DEVELOPMENT_BLOCKS,
    ARM_BASE,
    ARM_IMMEDIATE,
    ARM_RECLAIM,
    STATE_RECLAIM_WATCH,
    STATE_WAIT_BASE,
    V2WatchConfig,
    assert_development_only,
    evaluate_reclaim_watch,
    route_v2_extension,
)

RESEARCH_VERSION = "MIDPOINT_V2_STRUCTURAL_RECONSTRUCTION_V1"
EXPECTED_FRAMEWORK_VERSION = "OPENING_CANDLE_MIDPOINT_REVERSAL_FRAMEWORK_V1_1"
EXPECTED_STATE_VERSION = "MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2"


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def parse_underlying(value: str) -> tuple[str, Path]:
    if "|" not in value:
        raise ValueError("--underlying must be BLOCK|path")
    block, path = value.split("|", 1)
    block = block.strip()
    p = Path(path.strip())
    if not block or not p:
        raise ValueError("--underlying must be BLOCK|path")
    return block, p


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def first_existing(headers: list[str], candidates: tuple[str, ...]) -> str:
    lower_map = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    raise ValueError(
        f"None of columns {candidates!r} found. Available headers={headers!r}"
    )


def load_underlying_minute_closes(
    block: str,
    path: Path,
) -> dict[tuple[str, str], float]:
    """
    Index by (session_date, timestamp_iso). Flexible header detection keeps this
    adapter narrow while using the repo's actual raw CSV representation.
    """
    out: dict[tuple[str, str], float] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        ts_col = first_existing(
            headers,
            ("timestamp", "datetime", "time", "ts", "candle_timestamp"),
        )
        close_col = first_existing(
            headers,
            ("close", "close_price", "c", "spot_close"),
        )

        for row in reader:
            raw_ts = row.get(ts_col)
            raw_close = row.get(close_col)
            if raw_ts in (None, "") or raw_close in (None, ""):
                continue
            try:
                ts = parse_dt(str(raw_ts))
                close = float(raw_close)
            except (TypeError, ValueError):
                continue
            out[(ts.date().isoformat(), ts.isoformat())] = close
    return out


def framework_direction(event: dict[str, Any]) -> str | None:
    d = strength.direction_for_event(event)
    if d in {"BULLISH", "BEARISH"}:
        return d
    return None


def build_leakage_safe_checkpoint_rows(
    framework: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """
    Rebuild the exact checkpoint feature rows without using primary_outcome or
    outcome_label to select candidates.

    Future labels may remain in the source framework for later diagnostics, but
    are deliberately not copied into these rows.
    """
    rows: list[dict[str, Any]] = []
    source_events: dict[int, dict[str, Any]] = {}

    for idx, event in enumerate(framework.get("events") or []):
        block = str(event.get("block") or "")
        if block not in ALLOWED_DEVELOPMENT_BLOCKS:
            continue
        direction = framework_direction(event)
        if direction is None:
            continue

        source_events[idx] = event
        for cp in strength.CHECKPOINTS:
            snap = strength.snapshot_at(event, cp)
            if snap is None:
                continue

            ce = strength.oi_state(snap, "CE")
            pe = strength.oi_state(snap, "PE")
            oi = strength.classify_oi_pair(direction, ce, pe)
            oi.update(
                {
                    "ce_state": ce,
                    "pe_state": pe,
                    "ce_premium_change_5m_pct": strength.first_num(
                        snap,
                        ("ce_5m_premium_change_pct", "ce_premium_change_5m_pct"),
                    ),
                    "ce_oi_change_5m_pct": strength.first_num(
                        snap,
                        ("ce_5m_oi_change_pct", "ce_oi_change_5m_pct"),
                    ),
                    "pe_premium_change_5m_pct": strength.first_num(
                        snap,
                        ("pe_5m_premium_change_pct", "pe_premium_change_5m_pct"),
                    ),
                    "pe_oi_change_5m_pct": strength.first_num(
                        snap,
                        ("pe_5m_oi_change_pct", "pe_oi_change_5m_pct"),
                    ),
                }
            )

            rows.append(
                {
                    "block": block,
                    "session_date": event.get("session_date"),
                    "setup_type": event.get("setup_type"),
                    "direction": direction,
                    "primary_outcome": None,
                    "outcome_label": None,
                    "checkpoint_minutes": cp,
                    "checkpoint_label": "T0" if cp == 0 else f"T+{cp}",
                    "timestamp": snap.get("timestamp"),
                    "price_features": strength.extract_features(snap, direction),
                    "oi": oi,
                    "v2_source_event_index": idx,
                }
            )

    return rows, source_events


def prepare_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    original = diagnostics.ALLOWED_BLOCKS
    diagnostics.ALLOWED_BLOCKS = set(ALLOWED_DEVELOPMENT_BLOCKS)
    try:
        prepared = diagnostics.prepare_rows(rows)
    finally:
        diagnostics.ALLOWED_BLOCKS = original

    for r in prepared:
        if r.get("primary_outcome") is not None or r.get("outcome_label") is not None:
            raise ValueError("future outcome leaked into V2 checkpoint rows")
    return prepared


def build_t3_events(
    rows: list[dict[str, Any]],
    frozen_rules: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("checkpoint_minutes") in {1, 3}:
            groups[diagnostics.event_key(r)].append(r)

    events: list[dict[str, Any]] = []
    for group in groups.values():
        by_cp = {int(r["checkpoint_minutes"]): r for r in group}
        if 1 not in by_cp or 3 not in by_cp:
            continue

        t1, t3 = by_cp[1], by_cp[3]
        t1_obs = state.observe_t1(t1)
        t3_score = state.score_t3(t3, frozen_rules)
        t3_state = state.classify_t3(t3, t3_score)

        events.append(
            {
                "block": t3.get("block"),
                "session_date": t3.get("session_date"),
                "setup_type": t3.get("setup_type"),
                "direction": t3.get("direction"),
                "t1_observation_state": t1_obs["state"],
                "t3_state": t3_state,
                "t3_score": t3_score,
                "t3_timestamp": t3.get("timestamp"),
                "exact_oi_transition_t1_to_t3": t3.get(
                    "exact_oi_transition_t1_to_t3"
                ),
                "v2_source_event_index": t3.get("v2_source_event_index"),
            }
        )
    return events


def boundary_and_midpoint(
    source_event: dict[str, Any],
    direction: str,
) -> tuple[float, float]:
    midpoint = float(source_event["reference_midpoint"])
    if direction == "BULLISH":
        boundary = float(source_event["reference_high"])
    elif direction == "BEARISH":
        boundary = float(source_event["reference_low"])
    else:
        raise ValueError(f"unsupported direction {direction!r}")
    return boundary, midpoint


def closes_after_t3(
    *,
    block: str,
    session_date: str,
    t3_timestamp: str,
    underlying: dict[str, dict[tuple[str, str], float]],
    max_bars: int,
) -> list[float]:
    idx = underlying[block]
    t3 = parse_dt(t3_timestamp)
    closes: list[float] = []
    for i in range(1, max_bars + 1):
        ts = t3 + timedelta(minutes=i)
        value = idx.get((session_date, ts.isoformat()))
        if value is None:
            break
        closes.append(value)
    return closes


def reconstruct(
    *,
    framework: dict[str, Any],
    frozen_state: dict[str, Any],
    underlying: dict[str, dict[tuple[str, str], float]],
    config: V2WatchConfig,
) -> dict[str, Any]:
    if framework.get("research_version") != EXPECTED_FRAMEWORK_VERSION:
        raise ValueError(
            f"unexpected framework version={framework.get('research_version')!r}"
        )
    if frozen_state.get("research_version") != EXPECTED_STATE_VERSION:
        raise ValueError(
            f"unexpected frozen state version={frozen_state.get('research_version')!r}"
        )

    blocks = sorted(
        {
            str(e.get("block"))
            for e in framework.get("events") or []
            if e.get("block")
        }
    )
    assert_development_only(blocks)
    if set(blocks) != set(ALLOWED_DEVELOPMENT_BLOCKS):
        raise ValueError(
            "V2 development reconstruction requires TRAIN + OOS_A/B/C/D exactly; "
            f"got {blocks}"
        )

    rules = frozen_state.get("t3_train_only_rules")
    if not isinstance(rules, dict) or not rules:
        raise ValueError("frozen state missing t3_train_only_rules")

    leakage_guard = frozen_state.get("leakage_guard") or {}
    if not leakage_guard.get("thresholds_derived_from_train_only"):
        raise ValueError("frozen rules are not declared TRAIN-only")
    if leakage_guard.get("oos_h_used"):
        raise ValueError("frozen state unexpectedly declares OOS-H usage")

    checkpoint_rows, source_events = build_leakage_safe_checkpoint_rows(framework)
    prepared = prepare_rows(checkpoint_rows)
    t3_events = build_t3_events(prepared, rules)

    rows: list[dict[str, Any]] = []
    for ev in t3_events:
        idx = int(ev["v2_source_event_index"])
        src = source_events[idx]
        direction = str(ev["direction"])
        boundary, midpoint = boundary_and_midpoint(src, direction)

        max_watch = max(config.max_base_watch_bars, config.max_reclaim_watch_bars)
        closes = closes_after_t3(
            block=str(ev["block"]),
            session_date=str(ev["session_date"]),
            t3_timestamp=str(ev["t3_timestamp"]),
            underlying=underlying,
            max_bars=max_watch,
        )

        result = route_v2_extension(
            t3_state=str(ev["t3_state"]),
            direction=direction,
            boundary=boundary,
            midpoint=midpoint,
            closes_after_t3=closes,
            config=config,
        )

        pre_chain_result = result
        chained_reclaim = None
        chained_reclaim_start_bar_index = None
        absolute_confirmation_bar_index = result.confirmation_bar_index

        if (
            ev["t3_state"] == STATE_WAIT_BASE
            and result.final_state == STATE_RECLAIM_WATCH
        ):
            start = result.confirmation_bar_index or 0
            chained_reclaim_start_bar_index = start
            remaining = closes[start:]
            chained_reclaim = evaluate_reclaim_watch(
                original_direction=direction,
                boundary=boundary,
                midpoint=midpoint,
                closes_after_t3=remaining,
                config=config,
            )
            if chained_reclaim.entry_arm == ARM_RECLAIM:
                result = chained_reclaim
                if chained_reclaim.confirmation_bar_index is None:
                    raise ValueError(
                        "confirmed chained reclaim missing confirmation_bar_index"
                    )
                absolute_confirmation_bar_index = (
                    start + chained_reclaim.confirmation_bar_index
                )

        confirmation_timestamp = None
        if result.entry_arm in {ARM_BASE, ARM_RECLAIM}:
            if absolute_confirmation_bar_index is None:
                raise ValueError(
                    "V2 entry arm missing absolute confirmation bar index"
                )
            confirmation_timestamp = (
                parse_dt(str(ev["t3_timestamp"]))
                + timedelta(minutes=absolute_confirmation_bar_index + 1)
            ).isoformat()
        elif result.entry_arm == ARM_IMMEDIATE:
            confirmation_timestamp = str(ev["t3_timestamp"])

        rows.append(
            {
                **ev,
                "reference_colour": src.get("reference_colour"),
                "reference_high": src.get("reference_high"),
                "reference_low": src.get("reference_low"),
                "reference_midpoint": src.get("reference_midpoint"),
                "boundary": boundary,
                "post_t3_close_count": len(closes),
                "post_t3_closes": closes,
                "pre_chain_result": pre_chain_result.to_dict(),
                "chained_reclaim_start_bar_index": chained_reclaim_start_bar_index,
                "absolute_confirmation_bar_index": absolute_confirmation_bar_index,
                "confirmation_timestamp": confirmation_timestamp,
                "v2_result": result.to_dict(),
                "chained_reclaim_result": (
                    chained_reclaim.to_dict() if chained_reclaim else None
                ),
            }
        )

    t3_counts = Counter(str(r["t3_state"]) for r in rows)
    final_counts = Counter(str(r["v2_result"]["final_state"]) for r in rows)
    arm_counts = Counter(
        str(r["v2_result"]["entry_arm"])
        for r in rows
        if r["v2_result"]["entry_arm"] is not None
    )
    direction_arm_counts: dict[str, dict[str, int]] = {}
    for direction in ("BULLISH", "BEARISH"):
        c = Counter(
            str(r["v2_result"]["entry_arm"])
            for r in rows
            if r["direction"] == direction
            and r["v2_result"]["entry_arm"] is not None
        )
        direction_arm_counts[direction] = dict(sorted(c.items()))

    by_block: dict[str, dict[str, int]] = {}
    for block in sorted(ALLOWED_DEVELOPMENT_BLOCKS):
        c = Counter(
            str(r["v2_result"]["entry_arm"])
            for r in rows
            if r["block"] == block and r["v2_result"]["entry_arm"] is not None
        )
        by_block[block] = dict(sorted(c.items()))

    missing_continuous = sum(
        1
        for r in rows
        if r["t3_state"] in {STATE_WAIT_BASE, STATE_RECLAIM_WATCH}
        and r["post_t3_close_count"] == 0
    )

    return {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "baseline_entry_version": EXPECTED_STATE_VERSION,
        "blocks": blocks,
        "config": asdict(config),
        "checkpoint_row_count": len(checkpoint_rows),
        "prepared_checkpoint_row_count": len(prepared),
        "structural_event_count": len(rows),
        "t3_state_counts": dict(sorted(t3_counts.items())),
        "v2_final_state_counts": dict(sorted(final_counts.items())),
        "entry_arm_counts": dict(sorted(arm_counts.items())),
        "direction_arm_counts": direction_arm_counts,
        "block_arm_counts": by_block,
        "missing_post_t3_minute_data_count": missing_continuous,
        "rows": rows,
        "integrity": {
            "future_outcome_used_for_candidate_selection": False,
            "future_outcome_retained_in_v2_rows": False,
            "frozen_train_rules_loaded_not_rederived": True,
            "v1_continuation_path_modified": False,
            "underlying_minute_closes_used_after_t3": True,
            "oos_h_used": False,
            "pnl_used": False,
        },
        "governance": {
            "structural_research_only": True,
            "rule_promotion_performed": False,
            "option_economics_performed": False,
            "exit_policy_selection_performed": False,
            "paper_or_live_order_emission_allowed": False,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--framework", required=True)
    ap.add_argument("--frozen-state", required=True)
    ap.add_argument("--underlying", action="append", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    framework = load_json(Path(args.framework))
    frozen_state = load_json(Path(args.frozen_state))

    underlying_specs = [parse_underlying(v) for v in args.underlying]
    blocks = [b for b, _ in underlying_specs]
    assert_development_only(blocks)
    if set(blocks) != set(ALLOWED_DEVELOPMENT_BLOCKS):
        raise SystemExit(
            "Need underlying inputs for TRAIN + OOS_A/B/C/D exactly; "
            f"got {sorted(blocks)}"
        )

    underlying = {
        block: load_underlying_minute_closes(block, path)
        for block, path in underlying_specs
    }

    result = reconstruct(
        framework=framework,
        frozen_state=frozen_state,
        underlying=underlying,
        config=V2WatchConfig(),
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
