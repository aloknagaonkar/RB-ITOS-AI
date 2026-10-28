"""Read stored pricing previews without refreshing or admitting evidence."""
import json
from .evidence import FLAGS, readonly


def pricing_state(path):
    with readonly(path) as db:
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "preparation_plans" not in tables:
            total, rows = 0, []
        else:
            total = db.execute(
                "SELECT COUNT(*) FROM preparation_plans"
            ).fetchone()[0]
            rows = list(db.execute(
                "SELECT data FROM preparation_plans ORDER BY id LIMIT 25"
            ))

    items = []
    allowed = (
        "instrument", "profile", "raw_tick_size", "normalized_tick_rupees",
        "bid", "ask", "bid_and_ask_on_grid", "status", "reasons",
    )
    for row in rows:
        plan = json.loads(row[0])
        evidence = plan.get("evidence", {})
        pricing = evidence.get("pricing_preview")
        if pricing is not None and not isinstance(pricing, dict):
            raise ValueError("STORED_PRICING_SCHEMA_INVALID")
        items.append({
            "plan_id": plan["id"],
            "signal_at": plan.get("signal_at"),
            "direction": plan.get("direction"),
            "instrument": plan.get("instrument"),
            "quantity": plan.get("quantity"),
            "recorded_pricing_available": pricing is not None,
            "pricing": (
                {k: pricing[k] for k in allowed if k in pricing}
                if pricing is not None else None
            ),
            "preparation_blockers": evidence.get("preparation_blockers", []),
            "tick_units_verified": False,
            "executable_request_created": False,
            "entry_permission": False,
            "production_ready": False,
        })
    return {
        **FLAGS,
        "model": "HILEGA_STORED_PRICING_PREVIEW_V1",
        "total_plans": total,
        "returned_plans": len(items),
        "has_more": total > len(items),
        "items": items,
        "freshness_reassessed": False,
        "controller_checks_performed": False,
        "tick_units_verified": False,
        "executable_request_created": False,
        "production_ready": False,
    }
