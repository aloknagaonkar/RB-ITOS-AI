from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

MODEL = "CONTROL_FAILURE_INTRABAR_PERSISTENCE_CONTINUATION_V6_6"


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    return float(v)


def _b(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})


def directional_value(direction: str, raw_value: float | None) -> float | None:
    if raw_value is None:
        return None
    if direction == "BULLISH":
        return raw_value
    if direction == "BEARISH":
        return -raw_value
    raise ValueError(f"unsupported direction={direction!r}")


def max_consecutive_true(values: Iterable[bool]) -> int:
    best = cur = 0
    for value in values:
        if value:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def breadth_supportive(direction: str, bullish: int, bearish: int) -> bool:
    if direction == "BULLISH":
        return bullish > bearish
    if direction == "BEARISH":
        return bearish > bullish
    raise ValueError(f"unsupported direction={direction!r}")


def outcome_group(move15: float | None, move30: float | None) -> str:
    p15 = move15 is not None and move15 > 0
    p30 = move30 is not None and move30 > 0
    if p15 and p30:
        return "POSITIVE_15_AND_30"
    if p15 or p30:
        return "MIXED_15_30"
    return "NON_POSITIVE_15_AND_30"


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


@dataclass(frozen=True)
class EventMetrics:
    session_date: str
    known_direction: str
    move_start_time: str
    signal_checkpoint: str
    selected_wings: int
    move_15m: float | None
    move_30m: float | None
    outcome_group: str
    failure_count_5m: int
    max_consecutive_failure_count: int
    first_failure_minute_from_candle_start: int | None
    first_failure_ll_minutes: float | None
    decay_count_5m: int
    first_decay_minute_from_candle_start: int | None
    first_decay_ll_minutes: float | None
    directional_cum_price_m1: float | None
    directional_cum_price_m2: float | None
    directional_cum_price_m3: float | None
    directional_cum_price_m4: float | None
    directional_cum_price_m5: float | None
    next_1m_directional_after_first_failure: float | None
    next_2m_directional_after_first_failure: float | None
    next_1m_continues: bool | None
    next_2m_continues: bool | None
    atm_support_at_first_failure: bool | None
    atm_support_after_first_failure: bool
    first_atm_support_minute: int | None
    breadth_support_at_first_failure: bool | None
    breadth_support_after_first_failure: bool
    first_breadth_support_minute: int | None
    failure_repeats_after_first: bool


def build_event_metrics(minute_rows: list[dict[str, str]], summary: dict[str, str]) -> EventMetrics:
    direction = summary["known_direction"]
    rows = sorted(minute_rows, key=lambda r: int(r["minute_from_candle_start"]))
    if [int(r["minute_from_candle_start"]) for r in rows] != [1, 2, 3, 4, 5]:
        raise ValueError(f"expected exact minute offsets 1..5 for {summary['session_date']} {summary['signal_checkpoint']}")

    failures = [_b(r["direction_failure"]) for r in rows]
    decays = [_b(r["direction_decay"]) for r in rows]
    first_fail_idx = next((i for i, v in enumerate(failures) if v), None)
    first_decay_idx = next((i for i, v in enumerate(decays) if v), None)

    directional_cum = [directional_value(direction, _f(r["cumulative_spot_from_candle_start"])) for r in rows]
    directional_1m = [directional_value(direction, _f(r["spot_delta_1m"])) for r in rows]

    def atm_support(r: dict[str, str]) -> bool:
        return r.get("atm_state") == direction

    def breadth_support(r: dict[str, str]) -> bool:
        return breadth_supportive(direction, int(r["bullish_strikes"]), int(r["bearish_strikes"]))

    next1 = next2 = None
    next1_cont = next2_cont = None
    atm_at_fail = breadth_at_fail = None
    atm_after = breadth_after = False
    first_atm_support = first_breadth_support = None
    failure_repeats = False

    if first_fail_idx is not None:
        atm_at_fail = atm_support(rows[first_fail_idx])
        breadth_at_fail = breadth_support(rows[first_fail_idx])
        later = rows[first_fail_idx + 1 :]
        failure_repeats = any(failures[first_fail_idx + 1 :])

        for r in later:
            if atm_support(r):
                atm_after = True
                first_atm_support = int(r["minute_from_candle_start"])
                break
        for r in later:
            if breadth_support(r):
                breadth_after = True
                first_breadth_support = int(r["minute_from_candle_start"])
                break

        if first_fail_idx + 1 < len(rows):
            next1 = directional_1m[first_fail_idx + 1]
            next1_cont = next1 is not None and next1 > 0
        if first_fail_idx + 2 < len(rows):
            vals = [directional_1m[first_fail_idx + 1], directional_1m[first_fail_idx + 2]]
            if all(v is not None for v in vals):
                next2 = float(vals[0]) + float(vals[1])
                next2_cont = next2 > 0

    # If support already exists at first failure, capture that minute explicitly.
    if first_fail_idx is not None and atm_at_fail:
        first_atm_support = int(rows[first_fail_idx]["minute_from_candle_start"])
    if first_fail_idx is not None and breadth_at_fail:
        first_breadth_support = int(rows[first_fail_idx]["minute_from_candle_start"])

    move15 = _f(summary.get("move_15m"))
    move30 = _f(summary.get("move_30m"))

    return EventMetrics(
        session_date=summary["session_date"],
        known_direction=direction,
        move_start_time=summary["move_start_time"],
        signal_checkpoint=summary["signal_checkpoint"],
        selected_wings=int(summary["selected_wings"]),
        move_15m=move15,
        move_30m=move30,
        outcome_group=outcome_group(move15, move30),
        failure_count_5m=sum(failures),
        max_consecutive_failure_count=max_consecutive_true(failures),
        first_failure_minute_from_candle_start=(first_fail_idx + 1 if first_fail_idx is not None else None),
        first_failure_ll_minutes=(_f(rows[first_fail_idx]["minute_from_move_start"]) if first_fail_idx is not None else None),
        decay_count_5m=sum(decays),
        first_decay_minute_from_candle_start=(first_decay_idx + 1 if first_decay_idx is not None else None),
        first_decay_ll_minutes=(_f(rows[first_decay_idx]["minute_from_move_start"]) if first_decay_idx is not None else None),
        directional_cum_price_m1=directional_cum[0],
        directional_cum_price_m2=directional_cum[1],
        directional_cum_price_m3=directional_cum[2],
        directional_cum_price_m4=directional_cum[3],
        directional_cum_price_m5=directional_cum[4],
        next_1m_directional_after_first_failure=next1,
        next_2m_directional_after_first_failure=next2,
        next_1m_continues=next1_cont,
        next_2m_continues=next2_cont,
        atm_support_at_first_failure=atm_at_fail,
        atm_support_after_first_failure=atm_after,
        first_atm_support_minute=first_atm_support,
        breadth_support_at_first_failure=breadth_at_fail,
        breadth_support_after_first_failure=breadth_after,
        first_breadth_support_minute=first_breadth_support,
        failure_repeats_after_first=failure_repeats,
    )


def group_summary(events: list[EventMetrics], group_name: str) -> dict[str, Any]:
    xs = [e for e in events if e.outcome_group == group_name]
    def vals(attr: str) -> list[float]:
        out: list[float] = []
        for e in xs:
            v = getattr(e, attr)
            if v is not None:
                out.append(float(v))
        return out
    def rate(attr: str) -> float | None:
        eligible = [getattr(e, attr) for e in xs if getattr(e, attr) is not None]
        if not eligible:
            return None
        return 100.0 * sum(bool(v) for v in eligible) / len(eligible)

    return {
        "outcome_group": group_name,
        "events": len(xs),
        "median_failure_count_5m": median(vals("failure_count_5m")),
        "median_max_consecutive_failure_count": median(vals("max_consecutive_failure_count")),
        "median_first_failure_minute": median(vals("first_failure_minute_from_candle_start")),
        "median_directional_cum_price_m2": median(vals("directional_cum_price_m2")),
        "median_directional_cum_price_m3": median(vals("directional_cum_price_m3")),
        "median_directional_cum_price_m5": median(vals("directional_cum_price_m5")),
        "repeat_failure_rate_pct": rate("failure_repeats_after_first"),
        "next_1m_continuation_rate_pct": rate("next_1m_continues"),
        "next_2m_continuation_rate_pct": rate("next_2m_continues"),
        "atm_support_at_first_failure_rate_pct": rate("atm_support_at_first_failure"),
        "atm_support_after_first_failure_rate_pct": rate("atm_support_after_first_failure"),
        "breadth_support_at_first_failure_rate_pct": rate("breadth_support_at_first_failure"),
        "breadth_support_after_first_failure_rate_pct": rate("breadth_support_after_first_failure"),
        "median_move_15m": median(vals("move_15m")),
        "median_move_30m": median(vals("move_30m")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v6-5-minute-detail", default="data/historical-evidence/control-failure-intrabar-v6-5/intrabar-minute-detail-v6-5.csv")
    ap.add_argument("--v6-5-event-summary", default="data/historical-evidence/control-failure-intrabar-v6-5/intrabar-event-summary-v6-5.csv")
    ap.add_argument("--output-dir", default="data/historical-evidence/control-failure-intrabar-persistence-v6-6")
    args = ap.parse_args()

    minute_path = Path(args.v6_5_minute_detail)
    summary_path = Path(args.v6_5_event_summary)
    if not minute_path.exists():
        raise FileNotFoundError(minute_path)
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)

    minute_rows = load_csv(minute_path)
    summaries = load_csv(summary_path)

    by_key: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for r in minute_rows:
        key = (r["session_date"], r["known_direction"], r["signal_checkpoint"])
        by_key.setdefault(key, []).append(r)

    events: list[EventMetrics] = []
    for s in summaries:
        key = (s["session_date"], s["known_direction"], s["signal_checkpoint"])
        rows = by_key.get(key)
        if not rows:
            raise RuntimeError(f"missing V6.5 minute rows for {key}")
        events.append(build_event_metrics(rows, s))

    groups = ["POSITIVE_15_AND_30", "MIXED_15_30", "NON_POSITIVE_15_AND_30"]
    grouped = [group_summary(events, g) for g in groups]

    out = Path(args.output_dir)
    event_dicts = [asdict(e) for e in events]
    write_csv(out / "intrabar-persistence-event-detail-v6-6.csv", event_dicts, list(event_dicts[0].keys()) if event_dicts else [])
    write_csv(out / "intrabar-persistence-group-summary-v6-6.csv", grouped, list(grouped[0].keys()) if grouped else [])

    doc = {
        "model": MODEL,
        "evaluation_only": True,
        "signal_logic_changed": False,
        "threshold_optimization_performed": False,
        "definitions": {
            "failure_count_5m": "Number of one-minute rows in the critical 5m signal candle with direction_failure=true.",
            "max_consecutive_failure_count": "Longest adjacent run of direction_failure=true within the five one-minute rows.",
            "next_1m_directional_after_first_failure": "Direction-normalized spot change in the minute immediately after the first failure.",
            "next_2m_directional_after_first_failure": "Sum of direction-normalized spot changes in the next two minutes after the first failure when both exist.",
            "atm_support": "ATM one-minute OI state equals the known directional move.",
            "breadth_support": "More basket strikes support the known direction than oppose it.",
            "outcome_group": "Sign-only research grouping from V6.5 +15m/+30m directional follow-through; not a live rule.",
        },
        "events": event_dicts,
        "group_summary": grouped,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "intrabar-persistence-summary-v6-6.json").write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(f"model={MODEL} events={len(events)}")
    print("\n=== EVENT PERSISTENCE / CONTINUATION ===")
    print("DATE       DIR     F  CONSEC FIRST  D  CUM2   CUM3   CUM5   N1     N2     REP ATM-> BRD-> OUTCOME")
    for e in events:
        def fmt(v: float | None) -> str:
            return "—" if v is None else f"{v:+.2f}"
        print(
            f"{e.session_date} {e.known_direction:<7} {e.failure_count_5m:>1} "
            f"{e.max_consecutive_failure_count:>6} {str(e.first_failure_minute_from_candle_start or '—'):>5} "
            f"{e.decay_count_5m:>2} {fmt(e.directional_cum_price_m2):>6} {fmt(e.directional_cum_price_m3):>6} "
            f"{fmt(e.directional_cum_price_m5):>6} {fmt(e.next_1m_directional_after_first_failure):>6} "
            f"{fmt(e.next_2m_directional_after_first_failure):>6} "
            f"{'Y' if e.failure_repeats_after_first else '-':>3} "
            f"{'Y' if e.atm_support_after_first_failure else '-':>4} "
            f"{'Y' if e.breadth_support_after_first_failure else '-':>4} {e.outcome_group}"
        )

    print("\n=== OUTCOME GROUP COMPARISON (DESCRIPTIVE ONLY) ===")
    for g in grouped:
        print(
            f"{g['outcome_group']}: events={g['events']} "
            f"med_fail_count={g['median_failure_count_5m']} med_consec={g['median_max_consecutive_failure_count']} "
            f"med_first_fail={g['median_first_failure_minute']} "
            f"med_cum2={g['median_directional_cum_price_m2']} med_cum3={g['median_directional_cum_price_m3']} "
            f"med_cum5={g['median_directional_cum_price_m5']} "
            f"repeat={g['repeat_failure_rate_pct']}% n1_cont={g['next_1m_continuation_rate_pct']}% "
            f"n2_cont={g['next_2m_continuation_rate_pct']}% atm_after={g['atm_support_after_first_failure_rate_pct']}% "
            f"breadth_after={g['breadth_support_after_first_failure_rate_pct']}% "
            f"med15={g['median_move_15m']} med30={g['median_move_30m']}"
        )

    print("\nNo live thresholds are selected by V6.6; this is descriptive attribution only.")
    print(f"EVENT_CSV: {out / 'intrabar-persistence-event-detail-v6-6.csv'}")
    print(f"GROUP_CSV: {out / 'intrabar-persistence-group-summary-v6-6.csv'}")
    print(f"SUMMARY_JSON: {out / 'intrabar-persistence-summary-v6-6.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
