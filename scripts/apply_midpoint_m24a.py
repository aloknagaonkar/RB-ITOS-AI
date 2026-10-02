#!/usr/bin/env python3
from pathlib import Path

p = Path("backend/market_lab/midpoint_strategy/live_shadow_ui.py")
if not p.exists():
    raise SystemExit(f"STOP: not found: {p}")

backup = p.with_name(p.name + ".pre-m2-4a.bak")
if not backup.exists():
    backup.write_text(p.read_text())
    print("BACKUP:", backup)

text = p.read_text()

if "def _audit_ui_detail(" in text and "def _presentation_for_replay(" in text:
    print("M2.4A helpers already present; skipping helper insertion.")
else:
    marker = '\n\n@router.get("/status")\n'
    if marker not in text:
        raise SystemExit('STOP: /status marker not found')

    helpers = r'''

def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _raw_vwap_diff(row: dict[str, Any]) -> float | None:
    futures = _num(row.get("futures_price"))
    vwap = _num(row.get("futures_vwap"))
    if futures is None or vwap is None:
        return None
    return futures - vwap


def _option_intent(row: dict[str, Any]) -> str | None:
    direction = str(row.get("direction") or "").upper()
    if direction == "BULLISH":
        return "BUY CE"
    if direction == "BEARISH":
        return "BUY PE"
    return None


def _check(
    name: str,
    *,
    passed: bool | None,
    observed: str,
    required: str,
    why: str = "",
    gap: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "result": (
            "PASS"
            if passed is True
            else "FAIL"
            if passed is False
            else "INFO"
        ),
        "observed": observed,
        "required": required,
        "why": why,
        "gap": gap,
    }


def _audit_ui_detail(row: dict[str, Any]) -> dict[str, Any]:
    direction = str(row.get("direction") or "").upper()
    event_type = str(row.get("event_type") or "")
    reason = str(row.get("reason") or "")
    evidence = row.get("evidence") or {}

    price = _num(row.get("underlying_price"))
    midpoint = _num(row.get("midpoint"))
    boundary = _num(row.get("original_boundary"))
    high = _num(row.get("reference_high"))
    low = _num(row.get("reference_low"))

    futures = _num(row.get("futures_price"))
    vwap = _num(row.get("futures_vwap"))
    raw_diff = _raw_vwap_diff(row)
    directional_vwap = _num(row.get("directional_vwap_value"))

    structure_checks: list[dict[str, Any]] = []
    strategy_checks: list[dict[str, Any]] = []
    management_checks: list[dict[str, Any]] = []

    if price is not None and midpoint is not None and direction in ("BEARISH", "BULLISH"):
        if direction == "BEARISH":
            midpoint_pass = price <= midpoint
            required = f"close <= {midpoint:.2f}"
            gap_value = max(0.0, price - midpoint)
            gap = f"{gap_value:.2f} points lower required" if not midpoint_pass else ""
        else:
            midpoint_pass = price >= midpoint
            required = f"close >= {midpoint:.2f}"
            gap_value = max(0.0, midpoint - price)
            gap = f"{gap_value:.2f} points higher required" if not midpoint_pass else ""

        structure_checks.append(
            _check(
                "Midpoint structural close",
                passed=midpoint_pass,
                observed=f"close {price:.2f}",
                required=required,
                gap=gap,
            )
        )

    if price is not None and boundary is not None and direction in ("BEARISH", "BULLISH"):
        if direction == "BEARISH":
            boundary_pass = price < boundary
            required = f"close < {boundary:.2f}"
            gap_value = max(0.0, price - boundary)
            gap = f"{gap_value:.2f} points lower required" if not boundary_pass else ""
        else:
            boundary_pass = price > boundary
            required = f"close > {boundary:.2f}"
            gap_value = max(0.0, boundary - price)
            gap = f"{gap_value:.2f} points higher required" if not boundary_pass else ""

        structure_checks.append(
            _check(
                "Original boundary close",
                passed=boundary_pass,
                observed=f"close {price:.2f}",
                required=required,
                gap=gap,
            )
        )

    if raw_diff is not None and direction in ("BEARISH", "BULLISH"):
        if direction == "BEARISH":
            mature_pass = raw_diff < -5.0
            gap_value = max(0.0, raw_diff + 5.0)
            required = "raw futures - VWAP < -5.00"
            gap = (
                f"{gap_value:.2f} additional bearish VWAP points required"
                if not mature_pass else ""
            )
        else:
            mature_pass = raw_diff > 5.0
            gap_value = max(0.0, 5.0 - raw_diff)
            required = "raw futures - VWAP > +5.00"
            gap = (
                f"{gap_value:.2f} additional bullish VWAP points required"
                if not mature_pass else ""
            )

        strategy_checks.append(
            _check(
                "Mature directional VWAP",
                passed=mature_pass,
                observed=f"{raw_diff:+.2f}",
                required=required,
                gap=gap,
            )
        )

    candidate_a = evidence.get("candidate_a_at_boundary")
    if candidate_a is not None:
        strategy_checks.append(
            _check(
                "Fresh Candidate A at boundary",
                passed=bool(candidate_a),
                observed="TRUE" if candidate_a else "FALSE",
                required=(
                    "fresh directional VWAP transition: "
                    "BEAR prior >= -5 then current < -5; "
                    "BULL prior <= +5 then current > +5"
                ),
                why=(
                    "Fresh Candidate A owns the boundary."
                    if candidate_a
                    else "No fresh Candidate A at this boundary."
                ),
            )
        )

    if "still_beyond_original_boundary" in evidence:
        value = bool(evidence.get("still_beyond_original_boundary"))
        strategy_checks.append(
            _check(
                "Still beyond original boundary",
                passed=value,
                observed="YES" if value else "NO",
                required="must remain beyond original boundary during B watch",
                why="" if value else "B delayed confirmation cannot qualify after boundary is lost.",
            )
        )

    if "minutes_since_boundary_break" in evidence:
        minutes = _num(evidence.get("minutes_since_boundary_break"))
        if minutes is not None:
            strategy_checks.append(
                _check(
                    "B confirmation window",
                    passed=minutes <= 10.0,
                    observed=f"{minutes:.0f} min elapsed",
                    required="<= 10 minutes from original boundary break",
                    gap="" if minutes <= 10.0 else f"{minutes - 10.0:.0f} min beyond allowed window",
                )
            )

    if "condition_progress_positive" in evidence:
        value = bool(evidence.get("condition_progress_positive"))
        management_checks.append(
            _check(
                "Net directional progress",
                passed=value,
                observed="POSITIVE" if value else "NOT POSITIVE",
                required="> 0 at exact +10m classifier",
            )
        )

    if "condition_vwap_change_positive" in evidence:
        value = bool(evidence.get("condition_vwap_change_positive"))
        management_checks.append(
            _check(
                "Directional futures-VWAP change",
                passed=value,
                observed="POSITIVE" if value else "NOT POSITIVE",
                required="> 0 at exact +10m classifier",
            )
        )

    if "condition_prior_minute_vwap_change_negative" in evidence:
        value = bool(evidence.get("condition_prior_minute_vwap_change_negative"))
        management_checks.append(
            _check(
                "VWAP deterioration",
                passed=value,
                observed="NEGATIVE" if value else "NOT NEGATIVE",
                required="< 0 for DEGRADED",
            )
        )

    if "condition_rebreak" in evidence:
        management_checks.append(
            _check(
                "CAP20 target rebreak",
                passed=bool(evidence.get("condition_rebreak")),
                observed="YES" if evidence.get("condition_rebreak") else "NO",
                required="first strict close back through degraded target",
            )
        )

    if "condition_age_ge_10" in evidence:
        management_checks.append(
            _check(
                "CAP20 recovery age",
                passed=bool(evidence.get("condition_age_ge_10")),
                observed=str(evidence.get("minutes_since_recovery", "—")),
                required=">= 10 minutes since degraded-target recovery",
            )
        )

    if "condition_points_le_20" in evidence:
        management_checks.append(
            _check(
                "CAP20 rescue point cap",
                passed=bool(evidence.get("condition_points_le_20")),
                observed=str(row.get("directional_points") or "—"),
                required="directional move <= +20 at first eligible rebreak",
            )
        )

    if event_type == "BOUNDARY_OWNER_OTHER" and reason == "FRESH_CANDIDATE_A_AT_BOUNDARY":
        strategy_checks.append(
            _check(
                "Boundary ownership",
                passed=True,
                observed="FRESH A",
                required="Fresh Candidate A owns boundary; B/E not assigned",
            )
        )

    if event_type == "E_ENTRY":
        strategy_checks.append(
            _check(
                "Family E entry",
                passed=True,
                observed="E ENTRY",
                required="Candidate A false + mature directional VWAP",
            )
        )

    if event_type == "B_ENTRY":
        strategy_checks.append(
            _check(
                "Family B delayed entry",
                passed=True,
                observed="B ENTRY",
                required="full Candidate A appears within B watch while structure remains valid",
            )
        )

    if event_type == "B_WATCH_STARTED":
        strategy_checks.append(
            _check(
                "Family B watch",
                passed=True,
                observed="WATCH STARTED",
                required="Candidate A false + E not mature at boundary",
            )
        )

    if event_type == "PLUS20_PROOF":
        management_checks.append(
            _check(
                "+20 proof",
                passed=True,
                observed=f"{row.get('directional_points', '—')} directional points",
                required="first favorable intrabar excursion >= +20",
            )
        )

    if event_type == "RUNNER_CLASSIFICATION":
        management_checks.append(
            _check(
                "Runner classifier",
                passed=True,
                observed=str(row.get("result") or row.get("reason") or "—"),
                required="exact +10m classifier after +20 proof",
            )
        )

    if event_type == "DEGRADED_STARTED":
        management_checks.append(
            _check(
                "Degraded state",
                passed=True,
                observed="DEGRADED",
                required="drawdown from running MFE + VWAP deterioration",
            )
        )

    if event_type == "CAP20_RESCUE_TRIGGERED":
        management_checks.append(
            _check(
                "CAP20 rescue",
                passed=True,
                observed="SHADOW EXIT",
                required="eligible first rebreak with directional move <= +20",
            )
        )

    if event_type == "STRUCTURAL_TERMINAL":
        management_checks.append(
            _check(
                "Structural terminal",
                passed=True,
                observed=str(reason or "MIDPOINT INVALIDATION"),
                required="first adverse midpoint close",
            )
        )

    if raw_diff is None:
        vwap_position = "NOT AVAILABLE"
    elif raw_diff > 0:
        vwap_position = "ABOVE VWAP"
    elif raw_diff < 0:
        vwap_position = "BELOW VWAP"
    else:
        vwap_position = "AT VWAP"

    return {
        "market": {
            "nifty": price,
            "reference_type": row.get("reference_type"),
            "reference_high": high,
            "reference_low": low,
            "midpoint": midpoint,
            "boundary": boundary,
            "directional_points": _num(row.get("directional_points")),
        },
        "vwap": {
            "futures_close": futures,
            "futures_vwap": vwap,
            "raw_diff": raw_diff,
            "directional_value": directional_vwap,
            "position": vwap_position,
        },
        "strategy": {
            "owner": _display_owner(row),
            "direction": row.get("direction"),
            "event_type": event_type,
            "result": row.get("result"),
            "reason": reason,
        },
        "option": {
            "intent": _option_intent(row),
            "exact_contract_available": False,
            "expiry": None,
            "strike": None,
            "instrument_key": None,
            "entry_premium": None,
            "exit_premium": None,
            "note": (
                "Exact CE/PE contract selection is not part of the current "
                "Midpoint evidence. Intent only; no contract is fabricated."
            ),
        },
        "checks": {
            "structure": structure_checks,
            "strategy": strategy_checks,
            "management": management_checks,
        },
    }


def _presentation_for_replay(
    minutes: list[dict[str, Any]],
    timeline_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_minute: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in timeline_rows:
        by_minute[_minute_token(event.get("timestamp"))].append(event)

    active: dict[str, Any] | None = None
    result: list[dict[str, Any]] = []

    for minute in minutes:
        item = dict(minute)
        events = by_minute.get(_minute_token(minute.get("timestamp")), [])
        item["events"] = events

        presentation: dict[str, Any] | None = None

        for event in events:
            et = str(event.get("event_type") or "")

            if et in ("B_ENTRY", "E_ENTRY"):
                active = {
                    "family": event.get("family"),
                    "direction": event.get("direction"),
                    "entry_timestamp": event.get("timestamp"),
                    "entry_underlying": event.get("underlying_price"),
                    "plus20": False,
                    "classifier": None,
                    "degraded": False,
                    "recovered": False,
                }

            if active is not None:
                if et == "PLUS20_PROOF":
                    active["plus20"] = True
                elif et == "RUNNER_CLASSIFICATION":
                    active["classifier"] = event.get("result") or event.get("reason")
                elif et == "DEGRADED_STARTED":
                    active["degraded"] = True
                elif et == "DEGRADED_TARGET_RECOVERED":
                    active["recovered"] = True

        if active is not None:
            direction = str(active.get("direction") or "")
            entry = _num(active.get("entry_underlying"))
            current = _num(item.get("underlying_close"))

            directional_move = None
            if entry is not None and current is not None:
                directional_move = (
                    current - entry
                    if direction == "BULLISH"
                    else entry - current
                    if direction == "BEARISH"
                    else None
                )

            raw = None
            fc = _num(item.get("futures_close"))
            fv = _num(item.get("futures_vwap"))
            if fc is not None and fv is not None:
                raw = fc - fv

            presentation = {
                "status": "ACTIVE",
                "label": f"CONTINUE · {direction}_ACTIVE",
                "family": active.get("family"),
                "direction": direction,
                "entry_timestamp": active.get("entry_timestamp"),
                "entry_underlying": entry,
                "current_underlying": current,
                "directional_move": directional_move,
                "plus20": bool(active.get("plus20")),
                "classifier": active.get("classifier"),
                "degraded": bool(active.get("degraded")),
                "recovered": bool(active.get("recovered")),
                "option_intent": (
                    "BUY CE"
                    if direction == "BULLISH"
                    else "BUY PE"
                    if direction == "BEARISH"
                    else None
                ),
                "futures_close": fc,
                "futures_vwap": fv,
                "raw_vwap_diff": raw,
                "vwap_position": (
                    "ABOVE VWAP"
                    if raw is not None and raw > 0
                    else "BELOW VWAP"
                    if raw is not None and raw < 0
                    else "AT VWAP"
                    if raw == 0
                    else "NOT AVAILABLE"
                ),
            }

        terminal = any(
            str(e.get("event_type") or "")
            in ("CAP20_RESCUE_TRIGGERED", "STRUCTURAL_TERMINAL")
            for e in events
        )

        if terminal and presentation is not None:
            presentation = dict(presentation)
            presentation["status"] = "EXIT"
            presentation["label"] = "EXIT"

        item["presentation"] = presentation
        result.append(item)

        if terminal:
            active = None

    return result
'''
    text = text.replace(marker, helpers + marker, 1)

old_live = '            return {"model": MODEL, "event": row, "display_owner": _display_owner(row)}'
new_live = '''            enriched = dict(row)
            enriched["ui"] = _audit_ui_detail(row)
            return {
                "model": MODEL,
                "event": enriched,
                "display_owner": _display_owner(row),
            }'''

if old_live in text:
    text = text.replace(old_live, new_live, 1)
elif 'enriched["ui"] = _audit_ui_detail(row)' not in text:
    raise SystemExit("STOP: live audit-detail return not found")

old_hist = '''                "event": row,
                "display_owner": _display_owner(row),'''
new_hist = '''                "event": {**row, "ui": _audit_ui_detail(row)},
                "display_owner": _display_owner(row),'''

if old_hist in text:
    text = text.replace(old_hist, new_hist, 1)
elif '"ui": _audit_ui_detail(row)' not in text:
    raise SystemExit("STOP: historical audit-detail return not found")

old_merge = '    merged_minutes = _merge_minutes_with_events(minutes, projected)'
new_merge = '    merged_minutes = _presentation_for_replay(minutes, projected)'

if old_merge in text:
    text = text.replace(old_merge, new_merge, 1)
elif new_merge not in text:
    raise SystemExit("STOP: historical merge call not found")

p.write_text(text)
print("PATCHED:", p)
