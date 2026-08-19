from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_exit_level(row: dict[str, Any]) -> str:
    entry = _as_float(row.get("Entry"))
    current = _as_float(row.get("Current"))
    stop = _as_float(row.get("Stop"))
    target1 = _as_float(row.get("Target") or row.get("Target 1"))
    target2 = _as_float(row.get("Target 2"))

    if current is None:
        return "WAITING FOR PRICE"
    if stop is not None and current <= stop:
        return "AT / BELOW STOP"
    if target2 is not None and current >= target2:
        return "TARGET 2 REACHED"
    if target1 is not None and current >= target1:
        return "TARGET 1 REACHED"
    if entry is not None and current >= entry:
        return "PROFIT ZONE"
    if entry is not None:
        return "BETWEEN ENTRY AND STOP"
    return "WAITING FOR PRICE"


def enrich_open_trade_rows(rows: Iterable[Any]) -> list[Any]:
    enriched: list[Any] = []
    for source in rows:
        if not hasattr(source, "items"):
            enriched.append(source)
            continue

        row = dict(source)
        is_open_trade_row = {
            "Order",
            "Entry",
            "Current",
            "Stop",
            "Target",
            "Status",
        }.issubset(row)
        if not is_open_trade_row:
            enriched.append(source)
            continue

        entry = _as_float(row.get("Entry"))
        current = _as_float(row.get("Current"))
        move_pct = (
            ((current - entry) / entry) * 100.0
            if entry not in (None, 0.0) and current is not None
            else None
        )

        target1 = row.pop("Target", None)
        row["Move %"] = round(move_pct, 2) if move_pct is not None else None
        row["Current Exit Level"] = classify_exit_level(
            {**row, "Target 1": target1}
        )
        row["Target 1"] = target1
        row["Target 2"] = row.get("Target 2")
        row["Exit Mode"] = row.get("Exit Mode") or "ACTIVE POLICY"
        enriched.append(row)
    return enriched


def install(page_module: Any) -> None:
    """Enrich only the existing Paper Trading open-position dataframe rows."""

    module_name = str(getattr(page_module, "__name__", ""))
    if not module_name.endswith(".paper_trading"):
        return
    if getattr(page_module, "_open_trade_row_runtime_installed", False):
        return

    original: Callable[..., list[Any]] | None = getattr(
        page_module,
        "_arrow_safe_rows",
        None,
    )
    if original is None:
        return

    def wrapped(rows):
        return original(enrich_open_trade_rows(rows))

    page_module._arrow_safe_rows = wrapped
    page_module._open_trade_row_runtime_installed = True
