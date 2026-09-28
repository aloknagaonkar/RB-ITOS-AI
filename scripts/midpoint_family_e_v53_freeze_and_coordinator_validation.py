#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path("data/historical-evidence")
LIVE_AUDIT = Path("data/live-observation/midpoint-strategy-v1/audit.jsonl")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

OUTDIR = ROOT / "hilega-pcr-oi-support-research-v1" / "midpoint-family-e-v53"
OWNERSHIP_CSV = OUTDIR / "boundary-ownership-v53.csv"
SUMMARY_TXT = OUTDIR / "summary-v53.txt"
REPORT_JSON = OUTDIR / "report-v53.json"

THRESHOLD = 5.0
B_DELAY_MAX_MINUTES = 10
FRESH_OWNER = "OTHER_FRESH_A"
FAMILY_B = "B"
FAMILY_E = "E"


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def minute_key(dt):
    return dt.isoformat()


def parse_dt(ts):
    return datetime.fromisoformat(ts)


def directional_mature(direction: str, diff: float) -> bool:
    return diff < -THRESHOLD if direction == "BEARISH" else diff > THRESHOLD


def still_beyond_boundary(direction: str, close: float, high: float, low: float) -> bool:
    return close < low if direction == "BEARISH" else close > high


def structure_valid(direction: str, close: float, midpoint: float) -> bool:
    return close <= midpoint if direction == "BEARISH" else close >= midpoint


def classify_at_boundary(direction: str, t0: str, fut: dict[str, dict], v52) -> tuple[str, str, bool | None, float | None]:
    row = fut.get(t0)
    if row is None:
        return "UNAVAILABLE", "MISSING_FUTURES_AT_BOUNDARY", None, None

    diff = float(row["diff"])
    a0 = v52.candidate_a(direction, t0, fut)

    if a0 is True:
        return FRESH_OWNER, "FRESH_CANDIDATE_A_AT_BOUNDARY", True, diff

    if a0 is False and directional_mature(direction, diff):
        return FAMILY_E, "MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY", False, diff

    if a0 is False:
        return FAMILY_B, "DELAYED_CONFIRMATION_WATCH", False, diff

    return "UNAVAILABLE", "CANDIDATE_A_UNAVAILABLE", a0, diff


def evaluate_b_watch(ev: dict, u: dict[str, dict], fut: dict[str, dict], v52):
    t0 = ev["boundary_break_timestamp"]
    direction = ev["direction"]
    mid = float(ev["reference_midpoint"])
    high = float(ev["reference_high"])
    low = float(ev["reference_low"])

    start = parse_dt(t0)
    checks = []
    for delay in range(1, B_DELAY_MAX_MINUTES + 1):
        ts = minute_key(start + timedelta(minutes=delay))
        ub = u.get(ts)
        fb = fut.get(ts)
        if ub is None or fb is None:
            checks.append({"ts": ts, "delay": delay, "result": "MISSING_EXACT_MINUTE"})
            continue

        close = float(ub["close"])
        sv = structure_valid(direction, close, mid)
        beyond = still_beyond_boundary(direction, close, high, low)
        ca = v52.candidate_a(direction, ts, fut)
        full_a = bool(ca is True and sv and beyond)

        rec = {
            "ts": ts,
            "delay": delay,
            "structure_valid": sv,
            "still_beyond_original_boundary": beyond,
            "candidate_a": ca,
            "full_candidate_a": full_a,
        }

        if not sv:
            rec["result"] = "DIRECTIONAL_STRUCTURE_INVALIDATED"
            checks.append(rec)
            return {
                "entry_timestamp": None,
                "terminal": "STRUCTURE_INVALIDATED",
                "checks": checks,
            }

        if full_a:
            rec["result"] = "B_DELAYED_CONFIRMATION"
            checks.append(rec)
            return {
                "entry_timestamp": ts,
                "terminal": "B_ENTRY",
                "checks": checks,
            }

        rec["result"] = "WAIT"
        checks.append(rec)

    return {
        "entry_timestamp": None,
        "terminal": "B_DELAY_WINDOW_EXPIRED",
        "checks": checks,
    }


def read_explicit_block(block, v52):
    sessions = v52.load_manifest_sessions(block["manifest"])
    ss = set(sessions)
    u, uc = v52.load_explicit_underlying(block["underlying"], ss)
    f, fc = v52.load_explicit_futures(block["futures"], ss)
    if uc or fc:
        raise SystemExit(f"STOP: source conflicts in {block['name']}: underlying={uc} futures={fc}")

    framework = []
    for d in sessions:
        framework.extend(v52.build_framework_for_session(d, u[d]))
    return sessions, u, f, framework


def load_b4(v52, canon):
    _, u_raw, conflicts = canon.load_underlying()
    if conflicts:
        raise SystemExit(f"STOP: canonical B4 underlying conflicts={conflicts}")
    f_raw = canon.load_futures()

    u = {
        d: dict(rows) for d, rows in u_raw.items()
        if "2025-12-12" <= d <= "2026-09-08"
    }
    f = {
        d: dict(rows) for d, rows in f_raw.items()
        if "2025-12-12" <= d <= "2026-09-08"
    }
    framework = []
    for d in sorted(u):
        framework.extend(v52.build_framework_for_session(d, u[d]))
    return sorted(set(u) & set(f)), u, f, framework


def write_csv(path: Path, rows: list[dict]):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def replay_2026_09_28():
    if not LIVE_AUDIT.exists():
        return {
            "available": False,
            "reason": f"{LIVE_AUDIT} not found",
        }

    rows = []
    for line in LIVE_AUDIT.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("session_date") == "2026-09-28":
            rows.append(r)

    boundaries = [r for r in rows if r.get("event_type") == "BOUNDARY_BREAK"]
    watches = [r for r in rows if r.get("event_type") == "B_WATCH_STARTED"]

    out = {
        "available": True,
        "boundary_count": len(boundaries),
        "boundaries": [],
    }

    for b in boundaries:
        direction = b.get("direction")
        fp = b.get("futures_price")
        fv = b.get("futures_vwap")
        raw = None if fp is None or fv is None else float(fp) - float(fv)

        same_watch = next(
            (
                w for w in watches
                if w.get("direction") == direction
                and w.get("event_timestamp") == b.get("event_timestamp")
            ),
            None,
        )
        original_a_false = bool(
            same_watch
            and same_watch.get("result") == "ORIGINAL_EVENT_CANDIDATE_A_FALSE"
        )

        owner = None
        reason = None
        if original_a_false and raw is not None and directional_mature(direction, raw):
            owner = FAMILY_E
            reason = "MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY"
        elif original_a_false:
            owner = FAMILY_B
            reason = "DELAYED_CONFIRMATION_WATCH"
        else:
            owner = "OTHER_OR_UNRESOLVED"
            reason = "LIVE_AUDIT_DOES_NOT_PROVE_ORIGINAL_A_FALSE"

        out["boundaries"].append({
            "timestamp": b.get("event_timestamp"),
            "direction": direction,
            "raw_futures_vwap_diff": raw,
            "original_candidate_a_false": original_a_false,
            "v53_owner": owner,
            "v53_reason": reason,
        })

    return out


def main():
    v52 = import_module(V52, "midpoint_v52_1")
    canon = import_module(CANON, "midpoint_canon_v53")

    # Reuse V52.1's frozen deterministic block definitions.
    blocks = list(v52.BLOCKS)

    ownership = []
    block_summaries = {}

    print("MIDPOINT FAMILY E — V53 FREEZE + B/E COORDINATOR OWNERSHIP")
    print("=" * 100)
    print("RESEARCH ONLY — no runtime/live changes")
    print()

    # Canonical structural parity guard from V52.1.
    _, b4_u_raw, b4_conflicts = canon.load_underlying()
    if b4_conflicts:
        raise SystemExit(f"STOP: canonical B4 conflicts={b4_conflicts}")
    b4_u = {
        d: dict(rows) for d, rows in b4_u_raw.items()
        if "2025-12-12" <= d <= "2026-09-08"
    }
    v52.canonical_parity_check(canon, b4_u)
    print("PASS: canonical B4 structure parity")
    print()

    for block in blocks:
        name = block["name"]

        if block["manifest"] is None:
            sessions, u, fut, framework = load_b4(v52, canon)
        else:
            sessions, u, fut, framework = read_explicit_block(block, v52)

        counts = Counter()
        b_entries = 0
        b_expired = 0
        b_invalidated = 0

        for ev in framework:
            d = ev["session_date"]
            t0 = ev["boundary_break_timestamp"]
            if d not in u or d not in fut or t0 not in u[d] or t0 not in fut[d]:
                counts["UNAVAILABLE"] += 1
                continue

            owner, reason, a0, diff = classify_at_boundary(
                ev["direction"], t0, fut[d], v52
            )
            counts[owner] += 1

            row = {
                "block": name,
                "session_date": d,
                "direction": ev["direction"],
                "boundary_break_timestamp": t0,
                "reference_high": ev["reference_high"],
                "reference_midpoint": ev["reference_midpoint"],
                "reference_low": ev["reference_low"],
                "candidate_a_at_boundary": a0,
                "futures_vwap_diff_at_boundary": diff,
                "family_owner": owner,
                "selection_reason": reason,
                "b_entry_timestamp": None,
                "b_watch_terminal": None,
            }

            if owner == FAMILY_B:
                b = evaluate_b_watch(ev, u[d], fut[d], v52)
                row["b_entry_timestamp"] = b["entry_timestamp"]
                row["b_watch_terminal"] = b["terminal"]
                if b["terminal"] == "B_ENTRY":
                    b_entries += 1
                elif b["terminal"] == "B_DELAY_WINDOW_EXPIRED":
                    b_expired += 1
                elif b["terminal"] == "STRUCTURE_INVALIDATED":
                    b_invalidated += 1

            ownership.append(row)

        # Exclusivity assertion: one owner field per structural event.
        if sum(counts.values()) != len(framework):
            raise SystemExit(f"STOP: ownership accounting mismatch in {name}")

        block_summaries[name] = {
            "sessions": len(sessions),
            "framework_events": len(framework),
            "ownership": dict(counts),
            "b_entries": b_entries,
            "b_expired": b_expired,
            "b_structure_invalidated": b_invalidated,
        }

        print(name)
        print("-" * 100)
        print(f"sessions={len(sessions)} framework_events={len(framework)}")
        print(
            f"E={counts[FAMILY_E]}  "
            f"B_WATCH={counts[FAMILY_B]}  "
            f"FRESH_A_OTHER={counts[FRESH_OWNER]}  "
            f"UNAVAILABLE={counts['UNAVAILABLE']}"
        )
        print(
            f"B entries={b_entries} expired={b_expired} "
            f"structure_invalidated={b_invalidated}"
        )
        print()

    # Exactly one owner per row.
    bad = [
        r for r in ownership
        if r["family_owner"] not in {FAMILY_B, FAMILY_E, FRESH_OWNER, "UNAVAILABLE"}
    ]
    if bad:
        raise SystemExit(f"STOP: invalid owner rows={len(bad)}")

    replay = replay_2026_09_28()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(OWNERSHIP_CSV, ownership)

    report = {
        "model": "MIDPOINT_FAMILY_E_V53",
        "research_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
        "family_e_frozen_definition": {
            "candidate_a_at_boundary": False,
            "raw_futures_vwap_directional_threshold": {
                "BEARISH": "< -5",
                "BULLISH": "> +5",
            },
            "entry_timestamp": "boundary_break_timestamp",
            "entry_delay_minutes": 0,
            "streak_filter": None,
            "direction_specific_tuning": False,
            "post_entry_management": "SAME_AS_FAMILY_B_IN_V54_NOT_IMPLEMENTED_HERE",
        },
        "coordinator_boundary_ownership": {
            "FRESH_A_AT_BOUNDARY": FRESH_OWNER,
            "A_FALSE_AND_MATURE_VWAP": FAMILY_E,
            "A_FALSE_AND_NOT_MATURE_VWAP": FAMILY_B,
            "one_structural_event_exactly_one_owner": True,
        },
        "family_b": {
            "rule_changed": False,
            "watch_max_minutes": B_DELAY_MAX_MINUTES,
            "entry_requires_full_candidate_a": True,
        },
        "blocks": block_summaries,
        "replay_2026_09_28": replay,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT FAMILY E — V53 FREEZE + B/E COORDINATOR OWNERSHIP")
    lines.append("=" * 100)
    lines.append("RESEARCH ONLY — NO LIVE/RUNTIME CHANGE")
    lines.append("")
    lines.append("FROZEN FAMILY E")
    lines.append("-" * 100)
    lines.append("At structural boundary T0:")
    lines.append("  Candidate A at T0 = FALSE")
    lines.append("  BEARISH raw futures-VWAP diff < -5 OR BULLISH raw diff > +5")
    lines.append("  => owner=E, immediate entry at boundary")
    lines.append("  no streak filter, no direction-specific tuning")
    lines.append("")
    lines.append("BOUNDARY OWNERSHIP")
    lines.append("-" * 100)
    lines.append("fresh Candidate A at boundary        => OTHER_FRESH_A")
    lines.append("A false + mature directional VWAP    => E")
    lines.append("A false + not mature directional VWAP=> B watch")
    lines.append("one structural event => exactly one owner")
    lines.append("")

    for block in blocks:
        s = block_summaries[block["name"]]
        o = s["ownership"]
        lines.append(block["name"])
        lines.append(
            f"  framework={s['framework_events']} "
            f"E={o.get(FAMILY_E,0)} "
            f"B_WATCH={o.get(FAMILY_B,0)} "
            f"FRESH_A_OTHER={o.get(FRESH_OWNER,0)} "
            f"UNAVAILABLE={o.get('UNAVAILABLE',0)}"
        )
        lines.append(
            f"  B entries={s['b_entries']} "
            f"expired={s['b_expired']} "
            f"invalidated={s['b_structure_invalidated']}"
        )
        lines.append("")

    lines.append("2026-09-28 LIVE-AUDIT REPLAY")
    lines.append("-" * 100)
    if replay.get("available"):
        for x in replay.get("boundaries", []):
            lines.append(
                f"{x['timestamp']} {x['direction']} "
                f"raw_diff={x['raw_futures_vwap_diff']} "
                f"original_A_false={x['original_candidate_a_false']} "
                f"=> owner={x['v53_owner']} "
                f"reason={x['v53_reason']}"
            )
    else:
        lines.append(f"unavailable: {replay.get('reason')}")
    lines.append("")
    lines.append("NEXT")
    lines.append("-" * 100)
    lines.append(
        "V54 should apply the existing Family B post-entry management unchanged to E "
        "(+20 proof, exact +10m classifier, DEGRADED/CAP20, one reentry, structural terminal)."
    )
    lines.append("V53 itself does not modify or enable live runtime.")
    lines.append("")
    lines.append(f"OWNERSHIP CSV = {OWNERSHIP_CSV}")
    lines.append(f"REPORT JSON   = {REPORT_JSON}")
    lines.append(f"SUMMARY       = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
