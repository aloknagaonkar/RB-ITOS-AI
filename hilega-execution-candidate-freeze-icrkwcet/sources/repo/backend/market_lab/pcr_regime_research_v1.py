"""Leakage-guarded PCR Regime Research V1.

Purpose
-------
Describe where the already-frozen PCR Methodology V2 option candidates work
or fail across TRAIN + OOS_A/B/C/D.  This module does *not* create a live
signal, retune Stage2, retune target/stop, or consume OOS_E/F/G/H.

Frozen trading policy used only to label historical candidate outcomes:
- exact T0 ATM instrument from Methodology V2
- next-minute open
- +5% target
- -10% stop
- ambiguous same bar -> stop
- otherwise +15m close
- 0.50 percentage-point round-trip cost

Regime cuts are derived from development *feature distributions only*, never
from trade returns.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


RESEARCH_VERSION = "PCR_REGIME_RESEARCH_V1"
METHODOLOGY_VERSION = "PCR_RESEARCH_METHODOLOGY_V2"
CONFIDENCE_PROFILE = "FROZEN_D5_D15"
ENTRY_RULE = "NEXT_MINUTE_OPEN"
CONTRACT_RULE = "EXACT_T0_ATM_INSTRUMENT_NO_SUBSTITUTION"

TARGET_PCT = 5.0
STOP_PCT = -10.0
TIME_EXIT_MINUTES = 15
ROUND_TRIP_COST_PCT_POINTS = 0.50
REFERENCE_POLICY = "TARGET_5_STOP_10"

IST = timezone(timedelta(hours=5, minutes=30))

ALLOWED_DEVELOPMENT_BLOCKS = {
    "TRAIN",
    "OOS_A",
    "OOS_B",
    "OOS_C",
    "OOS_D",
}
FORBIDDEN_BLOCKS = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}
FORBIDDEN_FEATURE_PREFIXES = ("forward_change_", "future_")

PROMOTION_MIN_CANDIDATES = 25
PROMOTION_MIN_BLOCKS = 4
PROMOTION_MIN_POSITIVE_BLOCKS = 4
PROMOTION_MIN_PROFIT_FACTOR = 1.0
PROMOTION_MAX_SINGLE_BLOCK_PROFIT_SHARE = 0.50

ONE_WAY_DIMENSIONS = (
    "trend_regime",
    "volatility_regime",
    "momentum_alignment",
    "time_regime",
    "pcr_spot_alignment",
)
TWO_WAY_DIMENSIONS = (
    ("trend_regime", "momentum_alignment"),
    ("trend_regime", "volatility_regime"),
    ("momentum_alignment", "volatility_regime"),
    ("trend_regime", "time_regime"),
)


@dataclass(frozen=True)
class BlockInput:
    name: str
    methodology_path: Path
    backtest_path: Path
    evidence_path: Path
    positioning_path: Path


def normalize_block_name(name: str) -> str:
    return name.strip().upper().replace("-", "_")


def parse_block(value: str) -> BlockInput:
    parts = value.split("|")
    if len(parts) != 5:
        raise argparse.ArgumentTypeError(
            "--block must be "
            "NAME|METHODOLOGY_JSON|BACKTEST_JSON|EVIDENCE_CSV|POSITIONING_CSV"
        )

    name, methodology, backtest, evidence, positioning = parts
    name = normalize_block_name(name)

    if name in FORBIDDEN_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"{name} is forbidden for PCR Regime Research V1 construction"
        )
    if name not in ALLOWED_DEVELOPMENT_BLOCKS:
        raise argparse.ArgumentTypeError(
            f"Unsupported development block {name}. "
            f"Allowed: {sorted(ALLOWED_DEVELOPMENT_BLOCKS)}"
        )

    return BlockInput(
        name=name,
        methodology_path=Path(methodology),
        backtest_path=Path(backtest),
        evidence_path=Path(evidence),
        positioning_path=Path(positioning),
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "unavailable"}:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        # Historical NSE artifacts are local-market timestamps unless an
        # explicit offset says otherwise.
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def minute_key(session_date: str, timestamp: str) -> tuple[str, str]:
    dt = parse_dt(timestamp).replace(second=0, microsecond=0)
    return session_date, dt.isoformat()


def event_key(session_date: str, timestamp: str, direction: str) -> tuple[str, str, str]:
    d, ts = minute_key(session_date, timestamp)
    return d, ts, direction.upper()


def quantile_linear(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a quantile from an empty sequence")
    if not 0 <= q <= 1:
        raise ValueError("q must be between 0 and 1")
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def validate_methodology(payload: dict[str, Any], block: str) -> None:
    if payload.get("status") != "AVAILABLE":
        raise ValueError(f"{block}: methodology status is not AVAILABLE")
    if payload.get("methodology_version") != METHODOLOGY_VERSION:
        raise ValueError(f"{block}: unexpected methodology version")
    profile = payload.get("profile") or payload.get("confidence_profile")
    if profile != CONFIDENCE_PROFILE:
        raise ValueError(f"{block}: expected {CONFIDENCE_PROFILE}, got {profile!r}")

    guard = payload.get("leakage_guard") or {}
    expected = {
        "current_holdout_validation_input_used": False,
        "panel_any_confirmation_allowed": False,
        "moving_atm_substitution_allowed": False,
    }
    for key, value in expected.items():
        if guard.get(key) != value:
            raise ValueError(
                f"{block}: methodology leakage guard {key} "
                f"expected {value!r}, got {guard.get(key)!r}"
            )


def validate_backtest(payload: dict[str, Any], block: str) -> None:
    if payload.get("status") != "AVAILABLE":
        raise ValueError(f"{block}: backtest status is not AVAILABLE")
    if payload.get("methodology_version") != METHODOLOGY_VERSION:
        raise ValueError(f"{block}: unexpected backtest methodology version")
    if payload.get("confidence_profile") != CONFIDENCE_PROFILE:
        raise ValueError(f"{block}: unexpected backtest confidence profile")
    if payload.get("entry_rule") != ENTRY_RULE:
        raise ValueError(f"{block}: expected {ENTRY_RULE}")
    if payload.get("contract_selection_rule") != CONTRACT_RULE:
        raise ValueError(f"{block}: expected {CONTRACT_RULE}")
    if not isinstance(payload.get("trades"), list):
        raise ValueError(f"{block}: backtest must contain top-level trades array")


def evidence_index(rows: Sequence[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = minute_key(row["session_date"], row["timestamp"])
        if key in out:
            raise ValueError(f"Duplicate evidence minute: {key}")
        out[key] = row
    return out


def evidence_by_session(
    rows: Sequence[dict[str, str]],
) -> dict[str, dict[datetime, dict[str, str]]]:
    result: dict[str, dict[datetime, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        dt = parse_dt(row["timestamp"]).replace(second=0, microsecond=0)
        result[row["session_date"]][dt] = row
    return dict(result)


def positioning_index(
    rows: Sequence[dict[str, str]],
) -> dict[tuple[str, str, str], dict[str, str]]:
    """Index exact instrument observations at each minute.

    A CE and PE row are both represented by the same source row, so we create
    one lookup key per instrument side.
    """
    out: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        session, ts = minute_key(row["session_date"], row["timestamp"])
        for col in ("ce_instrument_key", "pe_instrument_key"):
            instrument = (row.get(col) or "").strip()
            if instrument:
                out[(session, ts, instrument)] = row
    return out


def methodology_event_index(payload: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for side in ("bearish", "bullish"):
        direction_node = (payload.get("directions") or {}).get(side) or {}
        for event in direction_node.get("events") or []:
            key = event_key(
                str(event["session_date"]),
                str(event["timestamp"]),
                str(event["direction"]),
            )
            if key in out:
                raise ValueError(f"Duplicate methodology event: {key}")
            out[key] = event
    return out


def past_spot_change(
    session_rows: dict[datetime, dict[str, str]],
    at: datetime,
    minutes: int,
) -> float | None:
    current = session_rows.get(at)
    previous = session_rows.get(at - timedelta(minutes=minutes))
    if current is None or previous is None:
        return None
    a = f(current.get("spot"))
    b = f(previous.get("spot"))
    if a is None or b is None:
        return None
    return a - b


def realized_vol_15m(
    session_rows: dict[datetime, dict[str, str]],
    at: datetime,
) -> float | None:
    """Population stdev of the prior fifteen exact 1-minute spot changes."""
    spots: list[float] = []
    for offset in range(15, -1, -1):
        row = session_rows.get(at - timedelta(minutes=offset))
        if row is None:
            return None
        value = f(row.get("spot"))
        if value is None:
            return None
        spots.append(value)
    changes = [spots[i] - spots[i - 1] for i in range(1, len(spots))]
    return statistics.pstdev(changes)


def _normalize_target_stop_label(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        label = value.upper().strip()
    elif isinstance(value, dict):
        # Backtest versions may use a direct status field or a compact boolean
        # representation.  Keep this explicit and fail if the schema changes.
        for key in ("outcome", "status", "result", "classification", "path_outcome"):
            if key in value and value[key] is not None:
                return _normalize_target_stop_label(value[key])

        target_first = value.get("target_first")
        stop_first = value.get("stop_first")
        ambiguous = value.get("ambiguous_same_bar")
        neither = value.get("neither_within_15m")

        if ambiguous is True:
            return "AMBIGUOUS_SAME_BAR"
        if target_first is True and stop_first is not True:
            return "TARGET_FIRST"
        if stop_first is True and target_first is not True:
            return "STOP_FIRST"
        if neither is True:
            return "NEITHER_WITHIN_15M"
        return None
    else:
        return None

    aliases = {
        "TARGET": "TARGET_FIRST",
        "TARGET_FIRST": "TARGET_FIRST",
        "STOP": "STOP_FIRST",
        "STOP_FIRST": "STOP_FIRST",
        "AMBIGUOUS": "AMBIGUOUS_SAME_BAR",
        "AMBIGUOUS_SAME_BAR": "AMBIGUOUS_SAME_BAR",
        "AMBIGUOUS_ASSUMED_STOP": "AMBIGUOUS_SAME_BAR",
        "NEITHER": "NEITHER_WITHIN_15M",
        "NEITHER_WITHIN_15M": "NEITHER_WITHIN_15M",
        "TIME_EXIT": "NEITHER_WITHIN_15M",
        "TIME_EXIT_15M": "NEITHER_WITHIN_15M",
    }
    return aliases.get(label)


def target_stop_label(trade: dict[str, Any]) -> str:
    target_stop = trade.get("target_stop")
    raw: Any = None
    if isinstance(target_stop, dict):
        raw = target_stop.get(REFERENCE_POLICY)
        if raw is None:
            # Some producer versions store the selected policy directly.
            direct = _normalize_target_stop_label(target_stop)
            if direct is not None:
                return direct
    else:
        raw = target_stop

    label = _normalize_target_stop_label(raw)
    if label is None:
        raise ValueError(
            "Unable to interpret trade target_stop for "
            f"{trade.get('session_date')} {trade.get('stage2_timestamp')} "
            f"{trade.get('direction')}; target_stop={target_stop!r}"
        )
    return label


def return_15m(trade: dict[str, Any]) -> float:
    values = trade.get("returns_pct")
    if not isinstance(values, dict):
        raise ValueError("trade returns_pct must be an object")
    for key in ("15m", "15", "return_15m", "15_minute"):
        if key in values:
            value = f(values[key])
            if value is not None:
                return value
    raise ValueError(f"15m return unavailable in returns_pct={values!r}")


def realized_trade(trade: dict[str, Any]) -> tuple[str, float, float]:
    label = target_stop_label(trade)

    if label == "TARGET_FIRST":
        exit_reason = "TARGET"
        gross = TARGET_PCT
    elif label in {"STOP_FIRST", "AMBIGUOUS_SAME_BAR"}:
        exit_reason = (
            "AMBIGUOUS_ASSUMED_STOP"
            if label == "AMBIGUOUS_SAME_BAR"
            else "STOP"
        )
        gross = STOP_PCT
    elif label == "NEITHER_WITHIN_15M":
        exit_reason = "TIME_EXIT_15M"
        gross = return_15m(trade)
    else:  # pragma: no cover - protected by target_stop_label
        raise AssertionError(label)

    return exit_reason, gross, gross - ROUND_TRIP_COST_PCT_POINTS


def time_regime(at: datetime) -> str:
    local = at.astimezone(IST).time().replace(tzinfo=None)
    if local < time(9, 45):
        return "PRE_REGIME_WINDOW"
    if local < time(11, 0):
        return "EARLY"
    if local < time(13, 30):
        return "MID"
    return "LATE"


def trend_regime(momentum_15m: float, abs_neutral_cut: float) -> str:
    if abs(momentum_15m) <= abs_neutral_cut:
        return "RANGE"
    return "UP" if momentum_15m > 0 else "DOWN"


def volatility_regime(vol: float, low_cut: float, high_cut: float) -> str:
    if vol <= low_cut:
        return "LOW"
    if vol >= high_cut:
        return "HIGH"
    return "NORMAL"


def momentum_alignment(direction: str, trend: str) -> str:
    if trend == "RANGE":
        return "NEUTRAL"
    expected = "DOWN" if direction == "BEARISH" else "UP"
    return "ALIGNED" if trend == expected else "AGAINST"


def pcr_spot_alignment(
    direction: str,
    moving_pcr_change_5m: float | None,
    spot_momentum_5m: float,
    spot_abs_neutral_cut_5m: float,
) -> str:
    if moving_pcr_change_5m is None:
        return "UNAVAILABLE"
    if abs(spot_momentum_5m) <= spot_abs_neutral_cut_5m:
        return "NEUTRAL"

    expected_pcr_sign = -1 if direction == "BEARISH" else 1
    expected_spot_sign = -1 if direction == "BEARISH" else 1
    pcr_sign = 1 if moving_pcr_change_5m > 0 else (-1 if moving_pcr_change_5m < 0 else 0)
    spot_sign = 1 if spot_momentum_5m > 0 else -1

    if pcr_sign == 0:
        return "NEUTRAL"
    if pcr_sign == expected_pcr_sign and spot_sign == expected_spot_sign:
        return "ALIGNED"
    if pcr_sign == expected_pcr_sign and spot_sign != expected_spot_sign:
        return "DIVERGENT"
    return "NEUTRAL"


def candidate_base_rows(block: BlockInput) -> list[dict[str, Any]]:
    methodology = load_json(block.methodology_path)
    backtest = load_json(block.backtest_path)
    evidence = load_csv(block.evidence_path)
    positioning = load_csv(block.positioning_path)

    validate_methodology(methodology, block.name)
    validate_backtest(backtest, block.name)

    events = methodology_event_index(methodology)
    evidence_exact = evidence_index(evidence)
    evidence_sessions = evidence_by_session(evidence)
    positioning_exact = positioning_index(positioning)

    out: list[dict[str, Any]] = []

    for trade in backtest["trades"]:
        direction = str(trade["direction"]).upper()
        key = event_key(
            str(trade["session_date"]),
            str(trade["stage2_timestamp"]),
            direction,
        )
        event = events.get(key)
        if event is None:
            raise ValueError(f"{block.name}: no exact methodology event for trade {key}")

        if event.get("confirmation_status") != "CONFIRMED":
            raise ValueError(f"{block.name}: backtest trade is not methodology-confirmed: {key}")

        if event.get("confidence_tier") not in {"HIGH", "VERY_HIGH"}:
            raise ValueError(f"{block.name}: backtest trade is not HIGH/VERY_HIGH: {key}")

        event_offset = event.get("first_confirmation_offset_minutes")
        trade_offset = trade.get("confirmation_offset_minutes")
        if event_offset != trade_offset:
            raise ValueError(
                f"{block.name}: confirmation offset mismatch for {key}: "
                f"event={event_offset!r} trade={trade_offset!r}"
            )

        confirmation_ts = str(trade["confirmation_timestamp"])
        confirmation_key = minute_key(str(trade["session_date"]), confirmation_ts)
        evidence_row = evidence_exact.get(confirmation_key)
        if evidence_row is None:
            raise ValueError(
                f"{block.name}: evidence missing at confirmation minute {confirmation_key}"
            )

        instrument = str(trade["instrument_key"])
        pos_row = positioning_exact.get(
            (confirmation_key[0], confirmation_key[1], instrument)
        )
        if pos_row is None:
            raise ValueError(
                f"{block.name}: exact positioning instrument missing at confirmation: "
                f"{confirmation_key} {instrument}"
            )

        frozen_strike = f(trade.get("frozen_t0_atm_strike"))
        pos_strike = f(pos_row.get("strike"))
        if frozen_strike is None or pos_strike is None or abs(frozen_strike - pos_strike) > 1e-9:
            raise ValueError(
                f"{block.name}: frozen T0 ATM strike mismatch for {key}: "
                f"trade={frozen_strike!r} positioning={pos_strike!r}"
            )

        session_rows = evidence_sessions[str(trade["session_date"])]
        at = parse_dt(confirmation_ts).replace(second=0, microsecond=0)
        m1 = past_spot_change(session_rows, at, 1)
        m5 = past_spot_change(session_rows, at, 5)
        m15 = past_spot_change(session_rows, at, 15)
        vol15 = realized_vol_15m(session_rows, at)

        if None in (m1, m5, m15, vol15):
            # Regime features intentionally require exact backward history.
            # Stage2 normally occurs after 09:45, so this should be exceptional.
            raise ValueError(
                f"{block.name}: backward regime features unavailable for "
                f"{trade['session_date']} {confirmation_ts}"
            )

        exit_reason, gross, net = realized_trade(trade)

        out.append(
            {
                "block": block.name,
                "session_date": str(trade["session_date"]),
                "stage2_timestamp": str(trade["stage2_timestamp"]),
                "confirmation_timestamp": confirmation_ts,
                "entry_timestamp": str(trade["entry_timestamp"]),
                "direction": direction,
                "option_side": str(trade["option_side"]),
                "outcome": trade.get("outcome"),
                "confidence_tier": str(trade["confidence_tier"]),
                "confidence_score": f(event.get("confidence_score")),
                "confirmation_offset_minutes": int(trade["confirmation_offset_minutes"]),
                "frozen_t0_atm_strike": frozen_strike,
                "instrument_key": instrument,
                "entry_premium": f(trade.get("entry_premium")),
                "spot": f(evidence_row.get("spot")),
                "spot_momentum_1m": float(m1),
                "spot_momentum_5m": float(m5),
                "spot_momentum_15m": float(m15),
                "spot_realized_vol_15m": float(vol15),
                "fixed_pcr": f(evidence_row.get("fixed_pcr")),
                "moving_pcr": f(evidence_row.get("moving_pcr")),
                "full_pcr": f(evidence_row.get("full_pcr")),
                "fixed_pcr_change_5m": f(evidence_row.get("fixed_pcr_change_5m")),
                "moving_pcr_change_5m": f(evidence_row.get("moving_pcr_change_5m")),
                "full_pcr_change_5m": f(evidence_row.get("full_pcr_change_5m")),
                "ce_5m_premium_change_pct": f(pos_row.get("ce_5m_premium_change_pct")),
                "ce_5m_oi_change_pct": f(pos_row.get("ce_5m_oi_change_pct")),
                "pe_5m_premium_change_pct": f(pos_row.get("pe_5m_premium_change_pct")),
                "pe_5m_oi_change_pct": f(pos_row.get("pe_5m_oi_change_pct")),
                "combined_5m": pos_row.get("combined_5m"),
                "path_outcome_5_10": target_stop_label(trade),
                "exit_reason": exit_reason,
                "gross_return_pct": gross,
                "net_return_pct": net,
                "mfe_pct_15m": f(trade.get("mfe_pct_15m")),
                "mae_pct_15m": f(trade.get("mae_pct_15m")),
            }
        )

    expected = sum(
        int(((backtest.get("directions") or {}).get(side) or {})
            .get("summary", {})
            .get("candidate_count", 0))
        for side in ("bearish", "bullish")
    )
    if len(out) != expected:
        raise ValueError(
            f"{block.name}: top-level trades count {len(out)} "
            f"does not match directional candidate total {expected}"
        )

    return out


def derive_cuts(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Feature-distribution-only cut points.

    No return/outcome/target-stop field is consulted here.
    """
    abs_m15 = [abs(float(r["spot_momentum_15m"])) for r in rows]
    abs_m5 = [abs(float(r["spot_momentum_5m"])) for r in rows]
    vols = [float(r["spot_realized_vol_15m"]) for r in rows]

    return {
        "trend_abs_spot_momentum_15m_q33": quantile_linear(abs_m15, 1 / 3),
        "spot_momentum_5m_abs_q33": quantile_linear(abs_m5, 1 / 3),
        "volatility_15m_q33": quantile_linear(vols, 1 / 3),
        "volatility_15m_q67": quantile_linear(vols, 2 / 3),
    }


def assign_regimes(row: dict[str, Any], cuts: dict[str, float]) -> dict[str, Any]:
    result = dict(row)

    trend = trend_regime(
        float(row["spot_momentum_15m"]),
        cuts["trend_abs_spot_momentum_15m_q33"],
    )
    vol = volatility_regime(
        float(row["spot_realized_vol_15m"]),
        cuts["volatility_15m_q33"],
        cuts["volatility_15m_q67"],
    )

    result["trend_regime"] = trend
    result["volatility_regime"] = vol
    result["momentum_alignment"] = momentum_alignment(str(row["direction"]), trend)
    result["time_regime"] = time_regime(parse_dt(str(row["confirmation_timestamp"])))
    result["pcr_spot_alignment"] = pcr_spot_alignment(
        str(row["direction"]),
        f(row.get("moving_pcr_change_5m")),
        float(row["spot_momentum_5m"]),
        cuts["spot_momentum_5m_abs_q33"],
    )
    return result


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses == 0:
        return None
    return gains / losses


def summarize_basic(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(r["net_return_pct"]) for r in rows]
    mfes = [float(v) for r in rows if (v := f(r.get("mfe_pct_15m"))) is not None]
    maes = [float(v) for r in rows if (v := f(r.get("mae_pct_15m"))) is not None]
    positives = sum(v > 0 for v in returns)

    exit_counts = {
        name: sum(r.get("exit_reason") == name for r in rows)
        for name in ("TARGET", "STOP", "AMBIGUOUS_ASSUMED_STOP", "TIME_EXIT_15M")
    }

    return {
        "candidate_count": len(rows),
        "positive_count": positives,
        "positive_pct": (100.0 * positives / len(rows)) if rows else None,
        "mean_net_return_pct": statistics.fmean(returns) if returns else None,
        "median_net_return_pct": statistics.median(returns) if returns else None,
        "sum_net_return_pct_points": sum(returns),
        "profit_factor": profit_factor(returns),
        "median_mfe_pct": statistics.median(mfes) if mfes else None,
        "median_mae_pct": statistics.median(maes) if maes else None,
        "target_count": exit_counts["TARGET"],
        "stop_count": exit_counts["STOP"],
        "ambiguous_assumed_stop_count": exit_counts["AMBIGUOUS_ASSUMED_STOP"],
        "time_exit_count": exit_counts["TIME_EXIT_15M"],
    }


def summarize_with_blocks(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    overall = summarize_basic(rows)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["block"])].append(row)

    by_block: dict[str, Any] = {}
    positive_mean_blocks = 0
    negative_mean_blocks = 0
    zero_mean_blocks = 0
    positive_profit_by_block: dict[str, float] = {}

    for block in sorted(groups):
        summary = summarize_basic(groups[block])
        by_block[block] = summary
        mean = summary["mean_net_return_pct"]
        if mean is not None and mean > 0:
            positive_mean_blocks += 1
        elif mean is not None and mean < 0:
            negative_mean_blocks += 1
        else:
            zero_mean_blocks += 1
        positive_profit_by_block[block] = max(
            0.0, float(summary["sum_net_return_pct_points"])
        )

    represented = len(groups)
    total_positive_profit = sum(positive_profit_by_block.values())
    largest_share = (
        max(positive_profit_by_block.values()) / total_positive_profit
        if total_positive_profit > 0 and positive_profit_by_block
        else None
    )

    consistency = (
        100.0 * positive_mean_blocks / represented if represented else None
    )

    promotion_checks = {
        "candidate_count_gte_25": len(rows) >= PROMOTION_MIN_CANDIDATES,
        "represented_in_gte_4_blocks": represented >= PROMOTION_MIN_BLOCKS,
        "positive_mean_in_gte_4_blocks": (
            positive_mean_blocks >= PROMOTION_MIN_POSITIVE_BLOCKS
        ),
        "pooled_mean_net_return_positive": (
            overall["mean_net_return_pct"] is not None
            and overall["mean_net_return_pct"] > 0
        ),
        "pooled_profit_factor_gt_1": (
            overall["profit_factor"] is not None
            and overall["profit_factor"] > PROMOTION_MIN_PROFIT_FACTOR
        ),
        "single_block_positive_profit_share_lte_50pct": (
            largest_share is not None
            and largest_share <= PROMOTION_MAX_SINGLE_BLOCK_PROFIT_SHARE
        ),
    }

    return {
        **overall,
        "development_block_count": represented,
        "positive_mean_block_count": positive_mean_blocks,
        "negative_mean_block_count": negative_mean_blocks,
        "zero_mean_block_count": zero_mean_blocks,
        "block_consistency_pct": consistency,
        "largest_single_block_positive_profit_share": largest_share,
        "by_block": by_block,
        "promotion_checks": promotion_checks,
        "candidate_hypothesis": all(promotion_checks.values()),
    }


def group_summary(
    rows: Sequence[dict[str, Any]],
    dimensions: Sequence[str],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(str(row.get(d, "UNAVAILABLE")) for d in dimensions)
        groups[key].append(row)

    output: list[dict[str, Any]] = []
    for key in sorted(groups):
        summary = summarize_with_blocks(groups[key])
        output.append(
            {
                "dimensions": dict(zip(dimensions, key)),
                **summary,
            }
        )
    return output


def analyze_direction(
    rows: Sequence[dict[str, Any]],
    direction: str,
) -> dict[str, Any]:
    selected = [r for r in rows if r["direction"] == direction]
    one_way = {
        dim: group_summary(selected, (dim,))
        for dim in ONE_WAY_DIMENSIONS
    }
    two_way = {
        " x ".join(dims): group_summary(selected, dims)
        for dims in TWO_WAY_DIMENSIONS
    }
    candidates = []
    for family, tables in (("one_way", one_way), ("two_way", two_way)):
        for name, entries in tables.items():
            for entry in entries:
                if entry["candidate_hypothesis"]:
                    candidates.append(
                        {
                            "family": family,
                            "table": name,
                            "dimensions": entry["dimensions"],
                            "candidate_count": entry["candidate_count"],
                            "mean_net_return_pct": entry["mean_net_return_pct"],
                            "profit_factor": entry["profit_factor"],
                            "positive_mean_block_count": entry[
                                "positive_mean_block_count"
                            ],
                            "development_block_count": entry[
                                "development_block_count"
                            ],
                            "largest_single_block_positive_profit_share": entry[
                                "largest_single_block_positive_profit_share"
                            ],
                        }
                    )
    candidates.sort(
        key=lambda x: (
            -(x["positive_mean_block_count"] or 0),
            -(x["profit_factor"] or 0),
            -(x["candidate_count"] or 0),
        )
    )
    return {
        "candidate_count": len(selected),
        "overall": summarize_with_blocks(selected),
        "one_way": one_way,
        "two_way": two_way,
        "promoted_candidate_hypotheses": candidates,
    }


def write_rows_csv(rows: Sequence[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    preferred = [
        "block",
        "session_date",
        "stage2_timestamp",
        "confirmation_timestamp",
        "entry_timestamp",
        "direction",
        "option_side",
        "confidence_tier",
        "confidence_score",
        "confirmation_offset_minutes",
        "frozen_t0_atm_strike",
        "instrument_key",
        "spot",
        "spot_momentum_1m",
        "spot_momentum_5m",
        "spot_momentum_15m",
        "spot_realized_vol_15m",
        "fixed_pcr",
        "moving_pcr",
        "full_pcr",
        "fixed_pcr_change_5m",
        "moving_pcr_change_5m",
        "full_pcr_change_5m",
        "trend_regime",
        "volatility_regime",
        "momentum_alignment",
        "time_regime",
        "pcr_spot_alignment",
        "combined_5m",
        "path_outcome_5_10",
        "exit_reason",
        "gross_return_pct",
        "net_return_pct",
        "mfe_pct_15m",
        "mae_pct_15m",
        "outcome",
    ]
    extra = sorted(set().union(*(r.keys() for r in rows)) - set(preferred))
    fields = preferred + extra
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Leakage-guarded PCR Regime Research V1 over "
            "TRAIN + OOS_A/B/C/D development candidates"
        )
    )
    parser.add_argument(
        "--block",
        action="append",
        required=True,
        type=parse_block,
        help=(
            "Development block: "
            "NAME|METHODOLOGY_JSON|BACKTEST_JSON|EVIDENCE_CSV|POSITIONING_CSV"
        ),
    )
    parser.add_argument("--output", required=True, help="Development analysis JSON")
    parser.add_argument("--csv-output", required=True, help="Per-candidate regime CSV")
    parser.add_argument("--cuts-output", required=True, help="Frozen development cuts JSON")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    blocks: list[BlockInput] = args.block
    names = [block.name for block in blocks]

    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate block names supplied: {names}")

    # Require the complete development set so cuts cannot accidentally be
    # derived from a cherry-picked subset.
    if set(names) != ALLOWED_DEVELOPMENT_BLOCKS:
        raise ValueError(
            "PCR Regime Research V1 construction requires exactly "
            f"{sorted(ALLOWED_DEVELOPMENT_BLOCKS)}; received {sorted(names)}"
        )

    base_rows: list[dict[str, Any]] = []
    block_counts: dict[str, int] = {}
    for block in blocks:
        rows = candidate_base_rows(block)
        block_counts[block.name] = len(rows)
        base_rows.extend(rows)

    cuts = derive_cuts(base_rows)
    rows = [assign_regimes(row, cuts) for row in base_rows]

    cuts_payload = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "source_blocks": sorted(names),
        "cut_point_source": "POOLED_DEVELOPMENT_FEATURE_DISTRIBUTION_ONLY",
        "profitability_used_to_define_cut_points": False,
        "feature_definitions": {
            "trend": (
                "RANGE when abs(backward exact 15m spot change) <= development "
                "q33 of abs(15m spot change); otherwise sign gives UP/DOWN"
            ),
            "volatility": (
                "population stdev of fifteen exact backward 1m spot changes; "
                "LOW <= q33, HIGH >= q67, otherwise NORMAL"
            ),
            "spot_5m_neutral": (
                "abs(backward exact 5m spot change) <= development q33 of "
                "abs(5m spot change)"
            ),
        },
        "cuts": cuts,
    }

    result = {
        "status": "AVAILABLE",
        "research_version": RESEARCH_VERSION,
        "research_status": "DEVELOPMENT_REGIME_ANALYSIS",
        "methodology_version": METHODOLOGY_VERSION,
        "confidence_profile": CONFIDENCE_PROFILE,
        "development_blocks": sorted(names),
        "development_candidate_counts": block_counts,
        "candidate_count": len(rows),
        "frozen_trade_policy": {
            "target_pct": TARGET_PCT,
            "stop_pct": STOP_PCT,
            "time_exit_minutes": TIME_EXIT_MINUTES,
            "ambiguous_same_bar": "ASSUME_STOP_FIRST",
            "round_trip_cost_pct_points": ROUND_TRIP_COST_PCT_POINTS,
            "entry_rule": ENTRY_RULE,
            "contract_selection_rule": CONTRACT_RULE,
        },
        "regime_definition": cuts_payload["feature_definitions"],
        "cut_points": cuts,
        "promotion_rule": {
            "candidate_count_min": PROMOTION_MIN_CANDIDATES,
            "development_blocks_min": PROMOTION_MIN_BLOCKS,
            "positive_mean_blocks_min": PROMOTION_MIN_POSITIVE_BLOCKS,
            "pooled_mean_net_return_must_be_positive": True,
            "pooled_profit_factor_must_be_gt": PROMOTION_MIN_PROFIT_FACTOR,
            "largest_single_block_positive_profit_share_max": (
                PROMOTION_MAX_SINGLE_BLOCK_PROFIT_SHARE
            ),
            "meaning": (
                "Promotion creates a retrospective candidate hypothesis only; "
                "it is not a validated trading strategy."
            ),
        },
        "leakage_guard": {
            "allowed_construction_blocks": sorted(ALLOWED_DEVELOPMENT_BLOCKS),
            "oos_e_f_g_h_allowed_for_regime_construction": False,
            "oos_h_used": False,
            "future_return_features_used_for_regimes": False,
            "forbidden_feature_prefixes": list(FORBIDDEN_FEATURE_PREFIXES),
            "regime_timestamp": "CONFIRMATION_TIMESTAMP_AT_OR_BEFORE_ENTRY",
            "cut_point_source": "DEVELOPMENT_FEATURE_DISTRIBUTION_ONLY",
            "profitability_used_to_define_cut_points": False,
            "exact_methodology_event_join": True,
            "exact_confirmation_evidence_join": True,
            "exact_confirmation_positioning_instrument_join": True,
            "panel_any_confirmation_allowed": False,
            "moving_atm_substitution_allowed": False,
        },
        "directions": {
            "bearish": analyze_direction(rows, "BEARISH"),
            "bullish": analyze_direction(rows, "BULLISH"),
        },
    }

    output = Path(args.output)
    csv_output = Path(args.csv_output)
    cuts_output = Path(args.cuts_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cuts_output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    cuts_output.write_text(json.dumps(cuts_payload, indent=2) + "\n", encoding="utf-8")
    write_rows_csv(rows, csv_output)

    print(
        json.dumps(
            {
                "status": result["status"],
                "research_version": RESEARCH_VERSION,
                "research_status": result["research_status"],
                "development_blocks": result["development_blocks"],
                "candidate_count": result["candidate_count"],
                "development_candidate_counts": block_counts,
                "bearish_candidate_hypothesis_count": len(
                    result["directions"]["bearish"]["promoted_candidate_hypotheses"]
                ),
                "bullish_candidate_hypothesis_count": len(
                    result["directions"]["bullish"]["promoted_candidate_hypotheses"]
                ),
                "output": str(output),
                "csv_output": str(csv_output),
                "cuts_output": str(cuts_output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
