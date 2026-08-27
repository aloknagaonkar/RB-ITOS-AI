from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 2) if denominator else None


def build_legacy_performance(
    *,
    signals: Iterable[Mapping[str, object]],
    orders: Iterable[Mapping[str, object]],
    maximum_records: int = 500,
) -> dict[str, object]:
    """Summarize bounded persisted legacy V2 signal-to-paper performance."""
    bounded_signals = list(signals)[:maximum_records]
    by_id = {
        str(row.get("signal_id")): row
        for row in bounded_signals
        if row.get("signal_id")
    }
    bounded_orders = [
        row for row in list(orders)[:maximum_records]
        if str(row.get("signal_id") or "") in by_id
    ]
    closed = [row for row in bounded_orders if str(row.get("status")) == "CLOSED"]
    pnl = [float(row.get("realized_pnl") or 0.0) for row in closed]
    entry_latencies: list[float] = []
    for order in bounded_orders:
        signal = by_id.get(str(order.get("signal_id") or ""), {})
        confirmed = _time(signal.get("confirmation_timestamp"))
        entered = _time(order.get("entry_timestamp"))
        if confirmed is not None and entered is not None:
            try:
                entry_latencies.append(
                    max(0.0, (entered - confirmed).total_seconds())
                )
            except TypeError:
                # Do not combine legacy naive timestamps with aware timestamps.
                continue
    wins = sum(value > 0 for value in pnl)
    losses = sum(value < 0 for value in pnl)
    return {
        "Signals": len(by_id),
        "Signals with paper entry": len({row.get("signal_id") for row in bounded_orders}),
        "Paper entries": len(bounded_orders),
        "Signal-to-entry conversion %": _pct(
            len({row.get("signal_id") for row in bounded_orders}), len(by_id)
        ),
        "Closed trades": len(closed),
        "Wins": wins,
        "Losses": losses,
        "Win rate %": _pct(wins, len(closed)),
        "Gross profit": round(sum(value for value in pnl if value > 0), 2),
        "Gross loss": round(sum(value for value in pnl if value < 0), 2),
        "Net realized P&L": round(sum(pnl), 2),
        "Average signal-to-entry seconds": (
            round(sum(entry_latencies) / len(entry_latencies), 3)
            if entry_latencies else None
        ),
        "Sample bounded at": maximum_records,
    }


def build_canonical_performance(
    history: Iterable[object],
    *,
    maximum_records: int = 100,
) -> dict[str, object]:
    """Summarize bounded canonical shadow outcomes without implying P&L."""
    rows = list(history)[:maximum_records]

    def value(row: object, name: str) -> str:
        raw = row.get(name) if isinstance(row, Mapping) else getattr(row, name, "")
        return str(raw or "").upper()

    allowed = sum(value(row, "admission_outcome") == "ALLOWED" for row in rows)
    bundles = sum(value(row, "bundle_available") in {"YES", "TRUE", "AVAILABLE"} for row in rows)
    parity_available = [value(row, "parity") for row in rows if value(row, "parity")]
    parity_matches = sum(item in {"MATCH", "MATCHED", "TRUE"} for item in parity_available)
    return {
        "Shadow observations": len(rows),
        "Allowed decisions": allowed,
        "Admission rate %": _pct(allowed, len(rows)),
        "Bundles created": bundles,
        "Parity observations": len(parity_available),
        "Parity matches": parity_matches,
        "Parity match rate %": _pct(parity_matches, len(parity_available)),
        "Paper P&L": "Not comparable — canonical is shadow/canary",
        "Sample bounded at": maximum_records,
    }


__all__ = ["build_canonical_performance", "build_legacy_performance"]
