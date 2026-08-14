from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping
import hashlib

import pandas as pd

from red_bar_lab.services.signal_trade_attribution import (
    SignalTradeAttributionRecord,
    link_candidate,
    link_opportunity,
    link_committee_decision,
    link_trade_entry,
    close_trade,
)
from red_bar_lab.services.signal_trade_attribution_store import (
    SignalTradeAttributionStore,
)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def _read(database, method: str, *args, **kwargs) -> list[dict[str, object]]:
    fn = getattr(database, method, None)
    if fn is None:
        return []
    attempts = (
        lambda: fn(*args, **kwargs),
        lambda: fn(*args),
        lambda: fn(),
    )
    for call in attempts:
        try:
            rows = call()
            return [dict(row) for row in (rows or [])]
        except TypeError:
            continue
        except Exception:
            return []
    return []


def _record_from_row(row: Mapping[str, object]) -> SignalTradeAttributionRecord:
    fields = SignalTradeAttributionRecord.__dataclass_fields__
    values = {
        name: row.get(name)
        for name in fields
        if name in row
    }
    values["supporting_signal_ids"] = tuple(
        row.get("supporting_signal_ids") or ()
    )
    values["supporting_setup_types"] = tuple(
        row.get("supporting_setup_types") or ()
    )
    values["execution_allowed"] = False
    return SignalTradeAttributionRecord(**values)


def _event_time(row: Mapping[str, object]) -> pd.Timestamp | None:
    for name in (
        "evaluated_at",
        "created_at",
        "updated_at",
        "executed_at",
        "entry_timestamp",
        "exit_timestamp",
        "timestamp",
    ):
        value = _timestamp(row.get(name))
        if value is not None:
            return value
    return None


def _within_bundle_window(
    bundle: Mapping[str, object],
    row: Mapping[str, object],
    *,
    grace_minutes: int = 45,
) -> bool:
    detected = _timestamp(bundle.get("detected_at"))
    fresh_until = _timestamp(bundle.get("fresh_until"))
    event = _event_time(row)
    if detected is None or event is None:
        return False
    upper = (
        fresh_until + pd.Timedelta(minutes=grace_minutes)
        if fresh_until is not None
        else detected + pd.Timedelta(minutes=60)
    )
    return detected <= event <= upper


def _direction_matches(
    bundle: Mapping[str, object],
    row: Mapping[str, object],
) -> bool:
    bundle_direction = str(bundle.get("direction") or "").upper()
    row_direction = str(row.get("direction") or "").upper()
    return bool(bundle_direction and row_direction == bundle_direction)


def _closest(
    bundle: Mapping[str, object],
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object] | None:
    detected = _timestamp(bundle.get("detected_at"))
    candidates = [
        dict(row)
        for row in rows
        if _direction_matches(bundle, row)
        and _within_bundle_window(bundle, row)
    ]
    if not candidates:
        return None
    if detected is None:
        return candidates[0]
    return min(
        candidates,
        key=lambda row: abs(
            (
                (_event_time(row) or detected) - detected
            ).total_seconds()
        ),
    )


class AttributionPipelineReconciler:
    """Attach existing paper-pipeline evidence to v4.3 setup bundles.

    This is an observational bridge. It does not submit candidates, approve
    Committee decisions, open positions, or close positions.
    """

    def __init__(
        self,
        *,
        database,
        runs_root: str | Path,
        grace_minutes: int = 45,
    ):
        self.database = database
        self.runs_root = Path(runs_root)
        self.grace_minutes = int(grace_minutes)

    def _ledger_files(self) -> list[Path]:
        folder = self.runs_root / "signal_trade_attribution_v43"
        return sorted(folder.glob("*.jsonl")) if folder.exists() else []

    def _pipeline_rows(self) -> dict[str, list[dict[str, object]]]:
        return {
            "selection": _read(
                self.database,
                "read_trade_selection_evaluations",
                limit=5000,
            ),
            "opportunity": _read(
                self.database,
                "read_opportunity_evaluations",
                limit=5000,
            ),
            "committee": _read(
                self.database,
                "read_institutional_execution_evaluations",
                limit=5000,
            ),
            "queue": _read(
                self.database,
                "read_execution_queue",
                limit=5000,
            ),
            "orders": _read(
                self.database,
                "read_paper_execution_orders",
                "PAPER-STD",
            ),
        }

    def reconcile(self) -> dict[str, int]:
        stats = {
            "ledgers_seen": 0,
            "candidate_links": 0,
            "opportunity_links": 0,
            "committee_links": 0,
            "trade_entry_links": 0,
            "trade_exit_links": 0,
        }
        pipeline = self._pipeline_rows()

        for ledger_path in self._ledger_files():
            store = SignalTradeAttributionStore(ledger_path)
            for raw in store.read_all():
                stats["ledgers_seen"] += 1
                record = _record_from_row(raw)
                bundle = raw
                changed = False

                selection = _closest(bundle, pipeline["selection"])
                pipeline_signal_id = None
                candidate_symbol = None
                instrument_token = None
                if selection is not None:
                    pipeline_signal_id = str(selection.get("signal_id") or "")
                    candidate_symbol = str(
                        selection.get("candidate_symbol") or ""
                    )
                    instrument_token = selection.get("instrument_token")
                    candidate_id = _stable_id(
                        "CAND",
                        pipeline_signal_id,
                        instrument_token,
                        selection.get("candidate_rank"),
                    )
                    if record.candidate_id != candidate_id:
                        record = link_candidate(
                            record,
                            candidate_id=candidate_id,
                            status=str(
                                selection.get("decision")
                                or selection.get("status")
                                or "EVALUATED"
                            ),
                            created_at=str(
                                selection.get("evaluated_at")
                                or selection.get("created_at")
                                or ""
                            ),
                        )
                        stats["candidate_links"] += 1
                        changed = True

                opportunity_rows = pipeline["opportunity"]
                if pipeline_signal_id:
                    opportunity_rows = [
                        row for row in opportunity_rows
                        if str(row.get("signal_id") or "") == pipeline_signal_id
                        and (
                            not candidate_symbol
                            or str(row.get("candidate_symbol") or "")
                            == candidate_symbol
                        )
                    ]
                opportunity = _closest(bundle, opportunity_rows)
                if opportunity is not None:
                    opportunity_id = _stable_id(
                        "OPP",
                        opportunity.get("scan_id"),
                        opportunity.get("signal_id"),
                        opportunity.get("candidate_symbol"),
                    )
                    if record.opportunity_id != opportunity_id:
                        record = link_opportunity(
                            record,
                            opportunity_id=opportunity_id,
                            status=str(
                                opportunity.get("decision")
                                or ("ELIGIBLE" if opportunity.get("eligible") else "REJECTED")
                            ),
                            created_at=str(
                                opportunity.get("evaluated_at")
                                or opportunity.get("created_at")
                                or ""
                            ),
                        )
                        stats["opportunity_links"] += 1
                        changed = True

                committee_rows = pipeline["committee"]
                if pipeline_signal_id:
                    committee_rows = [
                        row for row in committee_rows
                        if str(row.get("signal_id") or "") == pipeline_signal_id
                        and (
                            not candidate_symbol
                            or str(row.get("candidate_symbol") or "")
                            == candidate_symbol
                        )
                    ]
                committee = _closest(bundle, committee_rows)
                if committee is not None:
                    decision_id = _stable_id(
                        "COM",
                        committee.get("scan_id"),
                        committee.get("signal_id"),
                        committee.get("candidate_symbol"),
                    )
                    if record.committee_decision_id != decision_id:
                        record = link_committee_decision(
                            record,
                            decision_id=decision_id,
                            decision=str(
                                committee.get("decision") or "UNKNOWN"
                            ),
                            reason=(
                                str(committee.get("reason"))
                                if committee.get("reason") is not None
                                else None
                            ),
                            decided_at=str(
                                committee.get("evaluated_at")
                                or committee.get("created_at")
                                or ""
                            ),
                        )
                        stats["committee_links"] += 1
                        changed = True

                order_rows = pipeline["orders"]
                if pipeline_signal_id:
                    order_rows = [
                        row for row in order_rows
                        if str(row.get("signal_id") or "") == pipeline_signal_id
                    ]
                if instrument_token not in (None, ""):
                    matching = [
                        row for row in order_rows
                        if int(row.get("instrument_token") or 0)
                        == int(instrument_token or 0)
                    ]
                    if matching:
                        order_rows = matching
                order = _closest(bundle, order_rows)
                if order is not None:
                    order_id = str(order.get("order_id") or "")
                    entry_time = str(
                        order.get("entry_timestamp")
                        or order.get("entry_time")
                        or order.get("created_at")
                        or ""
                    )
                    if order_id and record.trade_id != order_id:
                        record = link_trade_entry(
                            record,
                            trade_id=order_id,
                            trade_mode="PAPER",
                            option_side=str(
                                order.get("option_type")
                                or (
                                    "CE" if record.direction == "BULLISH"
                                    else "PE"
                                )
                            ),
                            option_symbol=(
                                str(
                                    order.get("tradingsymbol")
                                    or order.get("symbol")
                                )
                                if (
                                    order.get("tradingsymbol")
                                    or order.get("symbol")
                                )
                                else None
                            ),
                            entry_time=entry_time,
                            entry_price=float(order.get("entry_price") or 0.0),
                        )
                        stats["trade_entry_links"] += 1
                        changed = True

                    status = str(order.get("status") or "").upper()
                    exit_time = order.get("exit_timestamp") or order.get("exit_time")
                    if (
                        record.trade_id
                        and status in {"CLOSED", "EXITED"}
                        and exit_time
                        and record.exit_time != str(exit_time)
                    ):
                        entry_price = float(order.get("entry_price") or 0.0)
                        exit_price = float(
                            order.get("exit_price")
                            or order.get("current_price")
                            or 0.0
                        )
                        quantity = int(order.get("quantity") or 0)
                        realized = order.get("realized_pnl")
                        if realized is None:
                            realized = (exit_price - entry_price) * quantity
                        pnl_pct = order.get("pnl_percentage")
                        if pnl_pct is None:
                            pnl_pct = (
                                (exit_price - entry_price) / entry_price * 100.0
                                if entry_price else 0.0
                            )
                        record = close_trade(
                            record,
                            exit_time=str(exit_time),
                            exit_price=exit_price,
                            realized_pnl=float(realized or 0.0),
                            pnl_percentage=float(pnl_pct or 0.0),
                            maximum_favorable_excursion=order.get(
                                "mfe_points"
                            ),
                            maximum_adverse_excursion=order.get(
                                "mae_points"
                            ),
                            target_hit=order.get("target_hit"),
                            stop_hit=order.get("stop_hit"),
                            exit_reason=str(
                                order.get("exit_reason")
                                or order.get("close_reason")
                                or "UNKNOWN"
                            ),
                        )
                        stats["trade_exit_links"] += 1
                        changed = True

                if changed:
                    payload = record.as_record()
                    payload["pipeline_signal_id"] = pipeline_signal_id
                    payload["pipeline_match_method"] = (
                        "DIRECTION_AND_FRESHNESS_WINDOW"
                    )
                    store.upsert(payload)

        return stats
