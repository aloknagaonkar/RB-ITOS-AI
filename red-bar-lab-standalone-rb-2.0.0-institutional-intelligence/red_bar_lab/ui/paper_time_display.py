from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def short_time(value):
    if value in (None, ""):
        return "—"
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        else:
            parsed = parsed.astimezone(IST)
        return parsed.strftime("%H:%M")
    except (TypeError, ValueError):
        return text.split("T", 1)[1][:5] if "T" in text else text


def install():
    from red_bar_lab.ui import active_trade_views

    original_trade_rows = active_trade_views._compact_trade_rows
    original_exit_rows = active_trade_views._compact_exit_rows

    def trade_rows(rows):
        compact = original_trade_rows(rows)
        for display, source in zip(compact, rows):
            display["Entry Time"] = short_time(source.get("entry_timestamp"))
        return compact

    def exit_rows(rows):
        compact = original_exit_rows(rows)
        for display, source in zip(compact, rows):
            display["Entry Time"] = short_time(source.get("entry_timestamp"))
            display["Exit Time"] = short_time(source.get("exit_timestamp"))
        return compact

    active_trade_views._compact_trade_rows = trade_rows
    active_trade_views._compact_exit_rows = exit_rows
