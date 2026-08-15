from __future__ import annotations


def summarize_trailing_audit(audit_rows) -> dict[str, float | int]:
    rows = list(audit_rows or ())
    trailing_net = sum(
        float(row.get("exit_price") or 0.0)
        - float(row.get("entry_price") or 0.0)
        for row in rows
    )
    baseline_net = sum(
        float(row.get("baseline_exit") or 0.0)
        - float(row.get("entry_price") or 0.0)
        for row in rows
    )
    protected = sum(float(row.get("protected_points") or 0.0) for row in rows)
    activated = sum(1 for row in rows if row.get("activated"))
    return {
        "trailing_audited_trades": len(rows),
        "trailing_activated_trades": activated,
        "trailing_net_points": round(trailing_net, 3),
        "baseline_net_points_for_trailing_set": round(baseline_net, 3),
        "trailing_protected_points": round(protected, 3),
    }


def attach_trailing_columns(replay_rows, audit_rows):
    rows = replay_rows
    if not isinstance(rows, list):
        return rows

    audit_by_signal = {
        str(row.get("signal_id")): row
        for row in (audit_rows or ())
        if row.get("signal_id") is not None
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        signal_id = str(row.get("Bundle") or row.get("signal_id") or "")
        audit = audit_by_signal.get(signal_id)
        if not audit:
            row.setdefault("Trailing Activated", False)
            row.setdefault("Trailing Exit", None)
            row.setdefault("Trailing Return %", None)
            row.setdefault("Trailing Exit Reason", None)
            row.setdefault("Trailing Protected Points", None)
            continue
        row["Trailing Activated"] = bool(audit.get("activated"))
        row["Trailing Exit"] = audit.get("exit_price")
        row["Trailing Return %"] = audit.get("return_pct")
        row["Trailing Exit Reason"] = audit.get("exit_reason")
        row["Trailing Protected Points"] = audit.get("protected_points")
    return rows
