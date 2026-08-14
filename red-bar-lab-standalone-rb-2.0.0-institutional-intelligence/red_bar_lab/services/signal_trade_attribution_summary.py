from __future__ import annotations

from typing import Iterable, Mapping


def _sum(rows, field):
    return round(
        sum(float(row.get(field) or 0.0) for row in rows),
        4,
    )


def summarize_by_primary_setup(
    records: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        grouped.setdefault(
            str(record.get("primary_setup_type") or "UNKNOWN"),
            [],
        ).append(record)

    output = []
    for setup_type, rows in sorted(grouped.items()):
        generated = len(rows)
        candidates = sum(bool(row.get("candidate_id")) for row in rows)
        opportunities = sum(bool(row.get("opportunity_id")) for row in rows)
        approved = sum(
            str(row.get("committee_decision") or "").upper()
            in {"APPROVED", "PASS", "ACCEPTED"}
            for row in rows
        )
        entered = sum(bool(row.get("trade_id")) for row in rows)
        successful = sum(row.get("outcome") == "SUCCESS" for row in rows)
        failed = sum(row.get("outcome") == "FAILURE" for row in rows)
        breakeven = sum(row.get("outcome") == "BREAKEVEN" for row in rows)
        completed = successful + failed + breakeven

        output.append(
            {
                "primary_setup_type": setup_type,
                "generated_bundles": generated,
                "candidates": candidates,
                "opportunities": opportunities,
                "committee_approved": approved,
                "entered_trades": entered,
                "successful": successful,
                "failed": failed,
                "breakeven": breakeven,
                "win_rate_pct": (
                    round(successful / completed * 100.0, 2)
                    if completed else None
                ),
                "total_realized_pnl": _sum(rows, "realized_pnl"),
                "average_mfe": (
                    round(
                        sum(
                            float(row.get("maximum_favorable_excursion"))
                            for row in rows
                            if row.get("maximum_favorable_excursion") is not None
                        )
                        / sum(
                            row.get("maximum_favorable_excursion") is not None
                            for row in rows
                        ),
                        4,
                    )
                    if any(
                        row.get("maximum_favorable_excursion") is not None
                        for row in rows
                    )
                    else None
                ),
                "average_mae": (
                    round(
                        sum(
                            float(row.get("maximum_adverse_excursion"))
                            for row in rows
                            if row.get("maximum_adverse_excursion") is not None
                        )
                        / sum(
                            row.get("maximum_adverse_excursion") is not None
                            for row in rows
                        ),
                        4,
                    )
                    if any(
                        row.get("maximum_adverse_excursion") is not None
                        for row in rows
                    )
                    else None
                ),
                "execution_allowed": False,
            }
        )
    return output


def funnel_summary(
    records: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    rows = list(records)
    return {
        "generated_bundles": len(rows),
        "candidates": sum(bool(row.get("candidate_id")) for row in rows),
        "opportunities": sum(bool(row.get("opportunity_id")) for row in rows),
        "committee_decisions": sum(
            bool(row.get("committee_decision_id")) for row in rows
        ),
        "entered_trades": sum(bool(row.get("trade_id")) for row in rows),
        "closed_trades": sum(
            row.get("outcome") in {"SUCCESS", "FAILURE", "BREAKEVEN"}
            for row in rows
        ),
        "successful": sum(row.get("outcome") == "SUCCESS" for row in rows),
        "failed": sum(row.get("outcome") == "FAILURE" for row in rows),
        "total_realized_pnl": _sum(rows, "realized_pnl"),
        "execution_allowed": False,
    }
