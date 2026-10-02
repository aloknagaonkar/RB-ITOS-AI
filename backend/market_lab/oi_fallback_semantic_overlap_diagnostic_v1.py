from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

MODEL = "OI_FALLBACK_SEMANTIC_OVERLAP_DIAGNOSTIC_V1"


def rows_from_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "items", "candles"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
    raise ValueError("No row list found in JSON payload")


def _f(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _s(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return str(value)
    return None


def _canonical_side(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.upper().strip()
    aliases = {
        "CALL": "CE",
        "C": "CE",
        "CE": "CE",
        "PUT": "PE",
        "P": "PE",
        "PE": "PE",
    }
    return aliases.get(v)


@dataclass(frozen=True)
class OIObservation:
    timestamp: str
    strike: float
    side: str
    oi: float

    @property
    def key(self) -> tuple[str, float, str]:
        return self.timestamp, self.strike, self.side


@dataclass(frozen=True)
class OverlapRow:
    session_date: str
    timestamp: str
    strike: float
    side: str
    positioning_oi: float
    option_ohlc_oi: float
    signed_difference: float
    absolute_difference: float
    relative_difference_vs_positioning: float | None
    absolute_relative_difference: float | None
    exact_match: bool
    within_0_1_pct: bool | None
    within_0_5_pct: bool | None
    within_1_pct: bool | None
    within_5_pct: bool | None


def load_positioning_observations(path: Path, session_date: str) -> list[OIObservation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[OIObservation] = []
    for row in rows_from_json(payload):
        ts = _s(row, "timestamp", "ts", "time")
        strike = _f(row, "strike", "strike_price")
        ce = _f(row, "ce_open_interest", "ce_oi")
        pe = _f(row, "pe_open_interest", "pe_oi")
        if not ts or not ts.startswith(session_date) or strike is None:
            continue
        if ce is not None:
            out.append(OIObservation(ts, strike, "CE", ce))
        if pe is not None:
            out.append(OIObservation(ts, strike, "PE", pe))
    if not out:
        raise ValueError(f"No usable positioning observations for {session_date} in {path}")
    return out


def load_option_ohlc_observations(path: Path, session_date: str) -> list[OIObservation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[OIObservation] = []
    for row in rows_from_json(payload):
        ts = _s(row, "timestamp", "ts", "time")
        strike = _f(row, "strike", "strike_price")
        side = _canonical_side(_s(row, "side", "option_type", "type"))
        oi = _f(row, "open_interest", "oi")
        if not ts or not ts.startswith(session_date) or strike is None or side is None or oi is None:
            continue
        out.append(OIObservation(ts, strike, side, oi))
    if not out:
        raise ValueError(f"No usable option-OHLC OI observations for {session_date} in {path}")
    return out


def _index_unique(observations: Iterable[OIObservation], source: str) -> dict[tuple[str, float, str], OIObservation]:
    index: dict[tuple[str, float, str], OIObservation] = {}
    duplicates: list[tuple[str, float, str]] = []
    for obs in observations:
        if obs.key in index:
            duplicates.append(obs.key)
        index[obs.key] = obs
    if duplicates:
        example = duplicates[0]
        raise ValueError(
            f"Duplicate {source} exact key(s) found; first={example}. "
            "Diagnostic refuses ambiguous exact observations."
        )
    return index


def compare_exact_overlap(
    session_date: str,
    positioning: Iterable[OIObservation],
    option_ohlc: Iterable[OIObservation],
) -> tuple[list[OverlapRow], dict[str, int]]:
    pos = _index_unique(positioning, "positioning")
    ohlc = _index_unique(option_ohlc, "option_ohlc")
    keys = sorted(set(pos) & set(ohlc))

    rows: list[OverlapRow] = []
    for key in keys:
        p = pos[key]
        o = ohlc[key]
        diff = o.oi - p.oi
        abs_diff = abs(diff)
        if p.oi == 0:
            rel = None
            abs_rel = None
            w01 = w05 = w1 = w5 = None
        else:
            rel = diff / abs(p.oi)
            abs_rel = abs(rel)
            w01 = abs_rel <= 0.001
            w05 = abs_rel <= 0.005
            w1 = abs_rel <= 0.01
            w5 = abs_rel <= 0.05

        rows.append(OverlapRow(
            session_date=session_date,
            timestamp=p.timestamp,
            strike=p.strike,
            side=p.side,
            positioning_oi=p.oi,
            option_ohlc_oi=o.oi,
            signed_difference=diff,
            absolute_difference=abs_diff,
            relative_difference_vs_positioning=rel,
            absolute_relative_difference=abs_rel,
            exact_match=(p.oi == o.oi),
            within_0_1_pct=w01,
            within_0_5_pct=w05,
            within_1_pct=w1,
            within_5_pct=w5,
        ))

    counts = {
        "positioning_observations": len(pos),
        "option_ohlc_observations": len(ohlc),
        "exact_overlap_observations": len(rows),
        "positioning_only_observations": len(set(pos) - set(ohlc)),
        "option_ohlc_only_observations": len(set(ohlc) - set(pos)),
    }
    return rows, counts


def _rate(rows: list[OverlapRow], attr: str) -> float | None:
    values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    if not values:
        return None
    return sum(bool(v) for v in values) / len(values)


def summarize_session(session_date: str, rows: list[OverlapRow], counts: dict[str, int]) -> dict[str, Any]:
    abs_diffs = [r.absolute_difference for r in rows]
    rels = [r.absolute_relative_difference for r in rows if r.absolute_relative_difference is not None]
    signed = [r.signed_difference for r in rows]

    side_counts = Counter(r.side for r in rows)
    side_summary: dict[str, Any] = {}
    for side in ("CE", "PE"):
        sr = [r for r in rows if r.side == side]
        srels = [r.absolute_relative_difference for r in sr if r.absolute_relative_difference is not None]
        side_summary[side] = {
            "overlap_count": len(sr),
            "exact_match_rate": _rate(sr, "exact_match"),
            "within_0_5_pct_rate": _rate(sr, "within_0_5_pct"),
            "within_1_pct_rate": _rate(sr, "within_1_pct"),
            "mean_absolute_relative_difference": mean(srels) if srels else None,
        }

    return {
        "session_date": session_date,
        **counts,
        "overlap_rate_vs_positioning": (
            counts["exact_overlap_observations"] / counts["positioning_observations"]
            if counts["positioning_observations"] else None
        ),
        "exact_match_count": sum(r.exact_match for r in rows),
        "exact_match_rate": _rate(rows, "exact_match"),
        "within_0_1_pct_rate": _rate(rows, "within_0_1_pct"),
        "within_0_5_pct_rate": _rate(rows, "within_0_5_pct"),
        "within_1_pct_rate": _rate(rows, "within_1_pct"),
        "within_5_pct_rate": _rate(rows, "within_5_pct"),
        "mean_absolute_difference": mean(abs_diffs) if abs_diffs else None,
        "median_absolute_difference": median(abs_diffs) if abs_diffs else None,
        "mean_absolute_relative_difference": mean(rels) if rels else None,
        "median_absolute_relative_difference": median(rels) if rels else None,
        "mean_signed_difference": mean(signed) if signed else None,
        "mean_signed_difference_interpretation": (
            "OPTION_OHLC_HIGHER_ON_AVERAGE" if signed and mean(signed) > 0
            else "OPTION_OHLC_LOWER_ON_AVERAGE" if signed and mean(signed) < 0
            else "NO_MEAN_BIAS" if signed else "NA"
        ),
        "zero_positioning_oi_overlap_count": sum(r.positioning_oi == 0 for r in rows),
        "side_overlap_counts": dict(side_counts),
        "by_side": side_summary,
    }


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def _parse_triplet(raw: str) -> tuple[str, Path, Path]:
    # DATE:POSITIONING_JSON:OPTION_OHLC_JSON
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "--input must be DATE:POSITIONING_JSON:OPTION_OHLC_JSON"
        )
    return parts[0], Path(parts[1]), Path(parts[2])


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only exact semantic overlap diagnostic between positioning OI "
            "and option-OHLC fallback OI."
        )
    )
    parser.add_argument(
        "--input", action="append", required=True, type=_parse_triplet,
        help="Repeatable DATE:POSITIONING_JSON:OPTION_OHLC_JSON",
    )
    parser.add_argument("--overlap-csv", required=True)
    parser.add_argument("--summary-json", required=True)
    args = parser.parse_args()

    all_rows: list[OverlapRow] = []
    sessions: list[dict[str, Any]] = []

    for session_date, positioning_path, option_path in args.input:
        positioning = load_positioning_observations(positioning_path, session_date)
        option_ohlc = load_option_ohlc_observations(option_path, session_date)
        rows, counts = compare_exact_overlap(session_date, positioning, option_ohlc)
        all_rows.extend(rows)
        sessions.append(summarize_session(session_date, rows, counts))

    all_rows.sort(key=lambda r: (r.session_date, r.timestamp, r.strike, r.side))

    all_rels = [r.absolute_relative_difference for r in all_rows if r.absolute_relative_difference is not None]
    overall = {
        "status": "PASS",
        "model": MODEL,
        "session_count": len(sessions),
        "overlap_row_count": len(all_rows),
        "exact_match_rate": _rate(all_rows, "exact_match"),
        "within_0_1_pct_rate": _rate(all_rows, "within_0_1_pct"),
        "within_0_5_pct_rate": _rate(all_rows, "within_0_5_pct"),
        "within_1_pct_rate": _rate(all_rows, "within_1_pct"),
        "within_5_pct_rate": _rate(all_rows, "within_5_pct"),
        "mean_absolute_relative_difference": mean(all_rels) if all_rels else None,
        "median_absolute_relative_difference": median(all_rels) if all_rels else None,
        "sessions": sessions,
        "interpretation_note": (
            "This diagnostic reports equivalence evidence only. It does not declare the "
            "fallback semantically valid or invalid and does not change trading logic."
        ),
    }

    _write_csv(Path(args.overlap_csv), [asdict(r) for r in all_rows])
    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(overall, indent=2), encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "model": MODEL,
        "sessions": len(sessions),
        "overlap_rows": len(all_rows),
        "overlap_csv": str(args.overlap_csv),
        "summary_json": str(args.summary_json),
    }, indent=2))


if __name__ == "__main__":
    main()
