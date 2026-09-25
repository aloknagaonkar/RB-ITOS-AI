from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import math

from .hilega_directional_trade_dashboard_v1 import (
    project_directional_shadow_dashboard,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


MODEL = "HILEGA_DIRECTIONAL_PARITY_V1"
STRATEGY_ID = "HILEGA_DIRECTIONAL_SHADOW_V1"


DECISION_FIELDS = (
    "bar_timestamp",
    "trade_owner_before",
    "trade_owner_after",
    "bullish_state",
    "bearish_state",
    "bullish_armed",
    "bearish_armed",
    "accepted_events",
    "suppressed_events",
    "note",
)

CUTOFF_FIELDS = (
    "cutoff_timestamp",
    "cutoff_open",
    "trade_owner_before",
    "trade_owner_after",
    "accepted_events",
    "suppressed_events",
)

TRADE_FIELDS = (
    "direction",
    "option_side",
    "signal_bar",
    "signal_boundary",
    "expiry",
    "atm",
    "status",
    "exit_reason",
    "pending_exit_boundary",
)

LEG_FIELDS = (
    "relation_to_atm",
    "strike",
    "side",
    "instrument_key",
    "entry_timestamp",
    "entry_open",
    "exit_timestamp",
    "exit_open",
    "realized_points",
)


def _equal(a: Any, b: Any, tolerance: float = 1e-6) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b

    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(
            float(a),
            float(b),
            rel_tol=1e-10,
            abs_tol=tolerance,
        )

    if isinstance(a, list) and isinstance(b, list):
        return (
            len(a) == len(b)
            and all(
                _equal(x, y, tolerance)
                for x, y in zip(a, b)
            )
        )

    if isinstance(a, dict) and isinstance(b, dict):
        return (
            a.keys() == b.keys()
            and all(
                _equal(a[k], b[k], tolerance)
                for k in a
            )
        )

    return a == b


def _diff(a: Any, b: Any, prefix: str = "", tolerance: float = 1e-6):
    if _equal(a, b, tolerance):
        return []

    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(a.keys() | b.keys()):
            path = f"{prefix}.{key}" if prefix else key

            if key not in a or key not in b:
                out.append({
                    "field": path,
                    "historical": a.get(key, "<ABSENT>"),
                    "live": b.get(key, "<ABSENT>"),
                })
            else:
                out.extend(
                    _diff(
                        a[key],
                        b[key],
                        path,
                        tolerance,
                    )
                )
        return out

    if isinstance(a, list) and isinstance(b, list):
        out = []

        for i in range(max(len(a), len(b))):
            path = f"{prefix}[{i}]"

            if i >= len(a) or i >= len(b):
                out.append({
                    "field": path,
                    "historical": (
                        a[i] if i < len(a) else "<ABSENT>"
                    ),
                    "live": (
                        b[i] if i < len(b) else "<ABSENT>"
                    ),
                })
            else:
                out.extend(
                    _diff(
                        a[i],
                        b[i],
                        path,
                        tolerance,
                    )
                )

        return out

    return [{
        "field": prefix,
        "historical": a,
        "live": b,
    }]


def _verified_rows(path: str | Path) -> list[dict]:
    store = ShadowStepAuditStoreV1(path)

    ok, issue = store.verify_chain()

    if not ok:
        raise ValueError(
            f"INVALID_HASH_CHAIN:{issue}"
        )

    return store.read_all()


def _session_rows(
    rows: list[dict],
    session_date: str,
) -> list[dict]:
    out = []

    for row in rows:
        payload = row.get("payload") or {}

        if (
            payload.get("strategy_id") not in
            (None, STRATEGY_ID)
        ):
            continue

        candidates = (
            row.get("checkpoint"),
            payload.get("bar_timestamp"),
            payload.get("signal_bar"),
            payload.get("cutoff_timestamp"),
            payload.get("session_date"),
            payload.get("original_signal_bar"),
        )

        if any(
            isinstance(x, str)
            and x.startswith(session_date)
            for x in candidates
        ):
            out.append(row)

    return out


def _decision_projection(rows: list[dict]) -> dict[str, dict]:
    out = {}

    for row in rows:
        if row.get("stage") != "DIRECTIONAL_DECISION":
            continue

        payload = row.get("payload") or {}
        checkpoint = (
            row.get("checkpoint")
            or payload.get("bar_timestamp")
        )

        if not checkpoint:
            continue

        projected = {
            key: payload.get(key)
            for key in DECISION_FIELDS
        }

        previous = out.get(checkpoint)

        if (
            previous is not None
            and not _equal(previous, projected)
        ):
            raise ValueError(
                f"CONFLICTING_DIRECTIONAL_DECISION:{checkpoint}"
            )

        out[checkpoint] = projected

    return out


def _cutoff_projection(rows: list[dict]) -> dict[str, dict]:
    out = {}

    for row in rows:
        if row.get("stage") != "DIRECTIONAL_SESSION_CUTOFF":
            continue

        if row.get("status") != "PROCESSED":
            continue

        payload = row.get("payload") or {}
        cutoff = payload.get("cutoff_timestamp")

        if not cutoff:
            continue

        projected = {
            key: payload.get(key)
            for key in CUTOFF_FIELDS
        }

        previous = out.get(cutoff)

        if (
            previous is not None
            and not _equal(previous, projected)
        ):
            raise ValueError(
                f"CONFLICTING_DIRECTIONAL_CUTOFF:{cutoff}"
            )

        out[cutoff] = projected

    return out


EXIT_REASON_ALIASES = {
    "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21":
        "RSI_CROSS_BELOW_WMA21",
    "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21":
        "RSI_CROSS_ABOVE_WMA21",
}


def _canonical_exit_reason(value):
    return EXIT_REASON_ALIASES.get(value, value)


def _trade_projection(rows: list[dict]) -> dict[tuple[str, str], dict]:
    dashboard = project_directional_shadow_dashboard(rows)

    out = {}

    for trade in dashboard["trades"]:
        key = (
            trade["direction"],
            trade["signal_bar"],
        )

        projected = {
            field: trade.get(field)
            for field in TRADE_FIELDS
        }

        # Historical lifecycle rows use the strategy exit_reason while
        # recovery rows may preserve the equivalent directional event_type.
        # Normalize only these known aliases for semantic parity.
        projected["exit_reason"] = _canonical_exit_reason(
            projected.get("exit_reason")
        )

        projected["legs"] = [
            {
                field: leg.get(field)
                for field in LEG_FIELDS
            }
            for leg in sorted(
                trade.get("legs", []),
                key=lambda x: (
                    x.get("relation_to_atm", 99),
                    str(x.get("instrument_key")),
                ),
            )
        ]

        out[key] = projected

    return out


def _compare_maps(
    historical: dict,
    live: dict,
    *,
    tolerance: float,
) -> dict:
    hist_keys = set(historical)
    live_keys = set(live)

    mismatches = []

    for key in sorted(
        hist_keys & live_keys,
        key=str,
    ):
        differences = _diff(
            historical[key],
            live[key],
            tolerance=tolerance,
        )

        if differences:
            mismatches.append({
                "key": list(key)
                if isinstance(key, tuple)
                else key,
                "differences": differences,
            })

    return {
        "historical_events": len(historical),
        "live_events": len(live),
        "compared_events": len(hist_keys & live_keys),
        "missing_in_live": [
            list(x) if isinstance(x, tuple) else x
            for x in sorted(
                hist_keys - live_keys,
                key=str,
            )
        ],
        "missing_in_historical": [
            list(x) if isinstance(x, tuple) else x
            for x in sorted(
                live_keys - hist_keys,
                key=str,
            )
        ],
        "mismatches": mismatches,
    }


def compare_directional_audits(
    *,
    historical_path: str | Path,
    live_path: str | Path,
    session_date: str,
    tolerance: float = 1e-6,
) -> dict:
    historical_rows = _session_rows(
        _verified_rows(historical_path),
        session_date,
    )

    live_rows = _session_rows(
        _verified_rows(live_path),
        session_date,
    )

    hist_decisions = _decision_projection(
        historical_rows
    )
    live_decisions = _decision_projection(
        live_rows
    )

    hist_cutoff = _cutoff_projection(
        historical_rows
    )
    live_cutoff = _cutoff_projection(
        live_rows
    )

    hist_trades = _trade_projection(
        historical_rows
    )
    live_trades = _trade_projection(
        live_rows
    )

    decision_cmp = _compare_maps(
        hist_decisions,
        live_decisions,
        tolerance=tolerance,
    )

    cutoff_cmp = _compare_maps(
        hist_cutoff,
        live_cutoff,
        tolerance=tolerance,
    )

    trade_cmp = _compare_maps(
        hist_trades,
        live_trades,
        tolerance=tolerance,
    )

    failures = any(
        section["mismatches"]
        or section["missing_in_live"]
        or section["missing_in_historical"]
        for section in (
            decision_cmp,
            cutoff_cmp,
            trade_cmp,
        )
    )

    insufficient = (
        decision_cmp["compared_events"] == 0
    )

    status = (
        "FAIL"
        if failures
        else "INSUFFICIENT_EVIDENCE"
        if insufficient
        else "PASS"
    )

    return {
        "model": MODEL,
        "session_date": session_date,
        "status": status,
        "directional_decisions": decision_cmp,
        "session_cutoff": cutoff_cmp,
        "option_trades": trade_cmp,
        "historical_records": len(historical_rows),
        "live_records": len(live_rows),
        "observation_only": True,
        "execution_enabled": False,
    }


def write_report(
    result: dict,
    path: str | Path,
) -> None:
    path = Path(path)
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n",
        encoding="utf-8",
    )


class HilegaDirectionalHistoricalFunctionalParityReplayV1:
    """Drive the production directional live coordinator using historical data."""

    def __init__(
        self,
        *,
        gateway,
        session_date,
        option_expiry,
        output_root,
        warmup_calendar_days=45,
        acquisition_today=None,
        warmup_cache_root=None,
    ):
        from .hilega_directional_live_shadow_v1 import (
            HilegaDirectionalLiveShadowCoordinatorV1,
        )
        from .hilega_milega_functional_parity_replay_v1 import (
            HistoricalParityMarketSourcesV1,
        )

        self.session_date = session_date
        self.output_root = Path(output_root)
        self.output_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.sources = HistoricalParityMarketSourcesV1(
            gateway,
            session_date,
            acquisition_today=acquisition_today,
        )

        self.coordinator = (
            HilegaDirectionalLiveShadowCoordinatorV1(
                market_sources=self.sources,
                step_audit_path=(
                    self.output_root / "step-audit.jsonl"
                ),
                health_path=(
                    self.output_root / "data-health.jsonl"
                ),
                cache_root=(
                    Path(warmup_cache_root)
                    if warmup_cache_root is not None
                    else self.output_root / "underlying-cache"
                ),
                warmup_calendar_days=warmup_calendar_days,
                option_expiry=option_expiry,
                option_candidate_wings=2,
                option_strike_step=50.0,
            )
        )

    def run(self) -> dict:
        from datetime import datetime, time, timedelta

        from .domain import IST

        if not self.sources._underlying:
            raise ValueError(
                "NO_TARGET_SESSION_UNDERLYING_CANDLES"
            )

        now = datetime.combine(
            self.session_date,
            time(9, 15, 30),
            tzinfo=IST,
        )

        # Match the production observation window used by the captured
        # directional audit: at 15:25:30 the completed target is 15:20.
        end = datetime.combine(
            self.session_date,
            time(15, 25, 30),
            tzinfo=IST,
        )

        processed = 0

        while now <= end:
            result = self.coordinator.process(now)

            if result.get("status") == "PROCESSED":
                processed += 1

            now += timedelta(minutes=1)

        if processed == 0:
            raise ValueError(
                "ZERO_TARGET_SESSION_5M_BARS_PROCESSED"
            )

        ok, issue = (
            self.coordinator.step_audit.verify_chain()
        )

        rows = self.coordinator.step_audit.read_all()

        decision_count = sum(
            r.get("stage") == "DIRECTIONAL_DECISION"
            and r.get("status") == "PROCESSED"
            for r in rows
        )

        return {
            "model":
                "HILEGA_DIRECTIONAL_HISTORICAL_FUNCTIONAL_PARITY_REPLAY_V1",
            "session_date":
                self.session_date.isoformat(),
            "processed_5m_bars":
                processed,
            "directional_decisions":
                decision_count,
            "audit_chain_ok":
                ok,
            "audit_chain_issue":
                issue,
            "audit_path":
                str(
                    self.output_root
                    / "step-audit.jsonl"
                ),
            "observation_only":
                True,
            "execution_enabled":
                False,
            "paper_order_enabled":
                False,
        }
