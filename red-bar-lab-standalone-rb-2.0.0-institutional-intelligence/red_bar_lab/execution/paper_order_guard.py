from __future__ import annotations

from red_bar_lab.storage.database import RedBarDatabase


class PaperOrderGuardError(ValueError):
    pass


def _guarded_insert(self, row):
    payload = dict(row)
    source = str(payload.get("execution_strategy_source") or "").upper().strip()
    source_enabled = getattr(self, "execution_source_enabled", None)
    if callable(source_enabled) and not source_enabled(source):
        raise PaperOrderGuardError(f"PAPER_SOURCE_DISABLED:{source or 'MISSING'}")

    account_id = str(payload.get("account_id") or "PAPER-STD")
    open_rows = list(self.read_open_paper_execution_orders(account_id))
    if len(open_rows) >= 5:
        raise PaperOrderGuardError("MAXIMUM_OPEN_TRADES_REACHED:5")

    option_type = str(payload.get("option_type") or "").upper().strip()
    same_direction = sum(
        1 for item in open_rows
        if str(item.get("option_type") or "").upper().strip() == option_type
    )
    if option_type and same_direction >= 3:
        raise PaperOrderGuardError(
            f"MAXIMUM_SAME_DIRECTION_TRADES_REACHED:3:{option_type}"
        )

    signal_id = str(payload.get("signal_id") or "").strip()
    same_signal = [
        item for item in open_rows
        if str(item.get("signal_id") or "").strip() == signal_id
    ]
    if signal_id and len(same_signal) >= 3:
        raise PaperOrderGuardError(
            f"MAXIMUM_OPEN_TRADES_PER_SIGNAL_REACHED:3:{signal_id}"
        )

    instrument_token = str(payload.get("instrument_token") or "").strip()
    if signal_id and any(
        str(item.get("instrument_token") or "").strip() == instrument_token
        for item in same_signal
    ):
        raise PaperOrderGuardError(
            f"DUPLICATE_PAPER_ORDER_SKIPPED:{signal_id}:{instrument_token}"
        )

    return _ORIGINAL_INSERT(self, payload)


_ORIGINAL_INSERT = RedBarDatabase.insert_paper_execution_order
if not getattr(RedBarDatabase, "_paper_order_guard_installed", False):
    RedBarDatabase.insert_paper_execution_order = _guarded_insert
    RedBarDatabase._paper_order_guard_installed = True
