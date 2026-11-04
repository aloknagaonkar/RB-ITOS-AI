from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .domain import IST
from .live_option_minute_source_v1 import CompletedOptionMinute
from .hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from .hilega_milega_pe_option_candidate_v1 import build_bearish_pe_candidate_set
from .hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
from .hilega_milega_pe_option_shadow_lifecycle_v1 import HilegaMilegaPEOptionShadowLifecycleV1

MODEL = "HILEGA_DIRECTIONAL_OPTION_RECOVERY_V1"
DEFAULT_AUDIT = Path("data/live-observation/hilega-directional-v1/step-audit.jsonl")
DEFAULT_EVIDENCE_ROOT = Path("data/live-observation/hilega-directional-market-evidence-v1")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(IST)


def _minute(value: datetime) -> datetime:
    return value.astimezone(IST).replace(second=0, microsecond=0)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            try:
                row = json.loads(line)
            except Exception as exc:
                raise ValueError(f"INVALID_JSONL:{path}:{line_no}:{type(exc).__name__}") from exc
            if isinstance(row, dict):
                out.append(row)
    return out


def _stage_info(stage: object) -> tuple[str | None, str | None]:
    raw = str(stage or "")
    for direction in ("BULLISH", "BEARISH"):
        prefix = f"{direction}_OPTION_SHADOW_"
        if raw.startswith(prefix):
            return direction, raw[len(prefix):]
    return None, None


def _directional_decisions(rows: list[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row.get("stage") != "DIRECTIONAL_DECISION":
            continue
        payload = row.get("payload") or {}
        ts = payload.get("bar_timestamp")
        if not isinstance(ts, str) or not ts.startswith(session):
            continue
        out.append({
            "sequence": row.get("sequence"),
            "bar_timestamp": ts,
            "accepted_events": payload.get("accepted_events") or [],
            "trade_owner_before": payload.get("trade_owner_before"),
            "trade_owner_after": payload.get("trade_owner_after"),
            "note": payload.get("note"),
        })
    out.sort(key=lambda x: _dt(x["bar_timestamp"]))
    return out


def _trade_events(rows: list[dict[str, Any]], session: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    out = {}
    accepted_kinds = {"START", "ENTRY_RETRY", "UPDATE", "EXIT", "EXIT_RETRY"}
    for row in rows:
        direction, kind = _stage_info(row.get("stage"))
        if direction is None or kind not in accepted_kinds:
            continue
        payload = row.get("payload") or {}
        signal_bar = payload.get("signal_bar")
        if not isinstance(signal_bar, str) or not signal_bar.startswith(session):
            continue
        out.setdefault((direction, signal_bar), []).append({
            "sequence": row.get("sequence"),
            "stage": row.get("stage"),
            "kind": kind,
            "status": row.get("status"),
            "payload": payload,
        })
    return out


def _extract_frozen_keys(issue: str) -> list[str]:
    return re.findall(r"(NSE_FO\|\d+):MISSING_ENTRY_MINUTE", issue or "")


def _find_exit(*, direction: str, signal_bar: str, decisions: list[dict[str, Any]]) -> dict[str, Any] | None:
    signal_dt = _dt(signal_bar)
    for decision in decisions:
        bar_dt = _dt(decision["bar_timestamp"])
        if bar_dt <= signal_dt:
            continue
        accepted = decision.get("accepted_events") or []
        exit_events = [str(event) for event in accepted if "EXIT" in str(event)]
        if decision.get("trade_owner_before") == direction and decision.get("trade_owner_after") != direction and exit_events:
            exit_signal = _dt(decision["bar_timestamp"])
            return {
                "exit_signal_bar": exit_signal.isoformat(),
                "exit_boundary": (exit_signal + timedelta(minutes=5)).isoformat(),
                "exit_event": exit_events[0],
                "decision_sequence": decision.get("sequence"),
            }
    return None


def _unresolved_trades(*, rows: list[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    decisions = _directional_decisions(rows, session)
    grouped = _trade_events(rows, session)
    unresolved = []
    for (direction, signal_bar), events in sorted(grouped.items(), key=lambda item: item[0][1]):
        if any(e["payload"].get("status") == "CLOSED" for e in events):
            continue
        if any(e["payload"].get("status") == "ACTIVE" for e in events):
            continue
        starts = [e for e in events if e["kind"] == "START" and e["payload"].get("status") == "INCOMPLETE"]
        if not starts:
            continue
        original = starts[0]["payload"]
        keys = _extract_frozen_keys(str(original.get("issue") or ""))
        if len(keys) != 5:
            unresolved.append({"status": "BLOCKED", "direction": direction, "signal_bar": signal_bar, "issue": f"ORIGINAL_FROZEN_KEY_COUNT_{len(keys)}"})
            continue
        exit_info = _find_exit(direction=direction, signal_bar=signal_bar, decisions=decisions)
        if exit_info is None:
            unresolved.append({"status": "BLOCKED", "direction": direction, "signal_bar": signal_bar, "issue": "DIRECTIONAL_EXIT_NOT_FOUND"})
            continue
        unresolved.append({
            "status": "UNRESOLVED",
            "direction": direction,
            "signal_bar": signal_bar,
            "entry_boundary": original.get("signal_boundary"),
            "signal_spot": float(original["signal_spot"]),
            "source": original.get("source"),
            "expiry": original.get("expiry"),
            "atm": float(original["atm"]),
            "instrument_keys": keys,
            **exit_info,
        })
    return unresolved


class EvidenceOptionStore:
    def __init__(self, path: Path) -> None:
        self.responses: dict[str, list[dict[str, Any]]] = {}
        with path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                row = json.loads(line)
                if row.get("kind") != "option" or row.get("status") != "OK":
                    continue
                args = row.get("args") or {}
                key = args.get("instrument_key")
                response = row.get("response")
                if key and isinstance(response, list):
                    self.responses.setdefault(str(key), []).append({"line_no": line_no, "rows": response})

    @staticmethod
    def _timestamps(rows: list[dict[str, Any]]) -> tuple[dict[datetime, dict[str, Any]], bool]:
        by_ts = {}
        duplicate = False
        for row in rows:
            raw_ts = row.get("timestamp")
            if not raw_ts:
                continue
            ts = _minute(_dt(str(raw_ts)))
            if ts in by_ts:
                duplicate = True
            by_ts[ts] = row
        return by_ts, duplicate

    def exact_response(self, *, instrument_key: str, start: datetime, end: datetime):
        start, end = _minute(start), _minute(end)
        expected = []
        ts = start
        while ts <= end:
            expected.append(ts)
            ts += timedelta(minutes=1)
        candidates = self.responses.get(instrument_key, [])
        for candidate in candidates:
            rows = candidate["rows"]
            by_ts, duplicate = self._timestamps(rows)
            if duplicate or any(ts not in by_ts for ts in expected):
                continue
            completed = []
            bad = False
            for ts in expected:
                raw = by_ts[ts]
                if str(raw.get("instrument_key")) != instrument_key:
                    bad = True; break
                try:
                    o, h, l, c = map(float, (raw["open"], raw["high"], raw["low"], raw["close"]))
                except Exception:
                    bad = True; break
                if min(o, h, l, c) <= 0:
                    bad = True; break
                v = raw.get("volume")
                completed.append(CompletedOptionMinute(instrument_key, ts, o, h, l, c, None if v is None else float(v)))
            if bad:
                continue
            return completed, {"evidence_line": candidate["line_no"], "response_row_count": len(rows), "start": start.isoformat(), "end": end.isoformat()}
        return None, {"issue": "NO_SINGLE_RECORDED_OK_RESPONSE_CONTAINS_FULL_EXACT_RANGE", "available_ok_responses": len(candidates), "start": start.isoformat(), "end": end.isoformat()}


def _contracts_for_trade(trade: dict[str, Any]) -> list[dict[str, Any]]:
    atm = float(trade["atm"])
    expiry = str(trade["expiry"])
    side = "CE" if trade["direction"] == "BULLISH" else "PE"
    keys = list(trade["instrument_keys"])
    if len(keys) != 5:
        raise ValueError("RECOVERY_REQUIRES_EXACT_FIVE_KEYS")
    return [{
        "instrument_key": key,
        "expiry": expiry,
        "strike_price": atm + offset * 50.0,
        "instrument_type": side,
        "option_type": side,
        "side": side,
    } for offset, key in zip(range(-2, 3), keys, strict=True)]


def _recover_trade(*, trade: dict[str, Any], evidence: EvidenceOptionStore) -> dict[str, Any]:
    if trade.get("status") == "BLOCKED":
        return dict(trade)
    direction = trade["direction"]
    signal_bar = _dt(trade["signal_bar"])
    entry_boundary = _dt(trade["entry_boundary"])
    exit_boundary = _dt(trade["exit_boundary"])
    if entry_boundary != _minute(signal_bar) + timedelta(minutes=5):
        return {**trade, "status": "BLOCKED", "issue": "ENTRY_BOUNDARY_NOT_SIGNAL_PLUS_5M"}
    if exit_boundary <= entry_boundary:
        return {**trade, "status": "BLOCKED", "issue": "EXIT_NOT_AFTER_ENTRY"}
    contracts = _contracts_for_trade(trade)
    expiry = date.fromisoformat(trade["expiry"])
    if direction == "BULLISH":
        candidate_set = build_bullish_ce_candidate_set(signal_spot=trade["signal_spot"], expiry=expiry, contracts=contracts, strike_step=50.0, wings=2)
        lifecycle = HilegaMilegaOptionShadowLifecycleV1()
    else:
        candidate_set = build_bearish_pe_candidate_set(signal_spot=trade["signal_spot"], expiry=expiry, contracts=contracts, strike_step=50.0, wings=2)
        lifecycle = HilegaMilegaPEOptionShadowLifecycleV1()
    if candidate_set.status != "AVAILABLE":
        return {**trade, "status": "BLOCKED", "issue": f"REBUILT_FROZEN_CANDIDATE_SET_NOT_AVAILABLE:{candidate_set.issue}"}
    if float(candidate_set.atm) != float(trade["atm"]):
        return {**trade, "status": "BLOCKED", "issue": f"AUDITED_ATM_MISMATCH:{trade['atm']}!={candidate_set.atm}"}
    rebuilt_keys = [c.instrument_key for c in candidate_set.candidates]
    if rebuilt_keys != list(trade["instrument_keys"]):
        return {**trade, "status": "BLOCKED", "issue": "FROZEN_KEY_ORDER_MISMATCH", "rebuilt_keys": rebuilt_keys}
    exact_rows = {}
    provenance = {}
    for key in rebuilt_keys:
        rows, source = evidence.exact_response(instrument_key=key, start=entry_boundary, end=exit_boundary)
        provenance[key] = source
        if rows is None:
            return {**trade, "status": "BLOCKED", "issue": f"{key}:{source['issue']}", "evidence": provenance}
        exact_rows[key] = rows
    def option_minutes(key: str):
        return list(exact_rows.get(key, []))
    started = lifecycle.start(signal_bar_ts=signal_bar, signal_spot=float(trade["signal_spot"]), source=trade.get("source"), candidate_set=candidate_set, option_minutes=option_minutes)
    if started.status != "ACTIVE" or not started.active or len(started.legs) != 5:
        return {**trade, "status": "BLOCKED", "issue": f"LIFECYCLE_START_FAILED:{started.status}:{started.issue}", "entry_snapshot": started.payload(), "evidence": provenance}
    through = exit_boundary - timedelta(minutes=1)
    updated = lifecycle.update(through_completed_minute=through, option_minutes=option_minutes)
    if updated is None or updated.status != "ACTIVE" or not updated.active or updated.issue:
        return {**trade, "status": "BLOCKED", "issue": "FULL_EXACT_PATH_RECONSTRUCTION_FAILED", "update_snapshot": None if updated is None else updated.payload(), "evidence": provenance}
    if updated.latest_completed_minute != through.isoformat():
        return {**trade, "status": "BLOCKED", "issue": "PATH_DID_NOT_REACH_EXIT_MINUS_1M", "latest_completed_minute": updated.latest_completed_minute, "expected": through.isoformat(), "evidence": provenance}
    closed = lifecycle.close(exit_boundary=exit_boundary, exit_reason=trade["exit_event"], option_minutes=option_minutes)
    if closed is None or closed.status != "CLOSED" or closed.active or len(closed.legs) != 5:
        return {**trade, "status": "BLOCKED", "issue": "EXACT_EXIT_RECONSTRUCTION_FAILED", "close_snapshot": None if closed is None else closed.payload(), "evidence": provenance}
    return {**trade, "status": "RECOVERABLE", "model": MODEL, "candidate_keys_verified": True, "full_exact_path_verified": True, "exact_exit_verified": True, "evidence": provenance, "recovered_snapshot": closed.payload()}


def build_report(*, session: str, audit_path: Path, evidence_path: Path) -> dict[str, Any]:
    unresolved = _unresolved_trades(rows=_read_jsonl(audit_path), session=session)
    evidence = EvidenceOptionStore(evidence_path)
    results = [_recover_trade(trade=t, evidence=evidence) for t in unresolved]
    recoverable = [x for x in results if x.get("status") == "RECOVERABLE"]
    blocked = [x for x in results if x.get("status") == "BLOCKED"]
    return {"status": "PASS" if not blocked else "INCOMPLETE", "model": MODEL, "mode": "DRY_RUN", "session_date": session, "audit_path": str(audit_path), "evidence_path": str(evidence_path), "unresolved_count": len(unresolved), "recoverable_count": len(recoverable), "blocked_count": len(blocked), "execution_enabled": False, "paper_order_enabled": False, "quantity": None, "audit_mutated": False, "trades": results}


def main() -> None:
    p = argparse.ArgumentParser(description=MODEL)
    p.add_argument("--session", required=True)
    p.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    p.add_argument("--evidence", type=Path)
    p.add_argument("--json-output", type=Path)
    p.add_argument("--dry-run", action="store_true", required=True)
    a = p.parse_args()
    evidence_path = a.evidence or (DEFAULT_EVIDENCE_ROOT / f"{a.session}.jsonl")
    if not a.audit.exists():
        raise SystemExit(f"AUDIT_NOT_FOUND:{a.audit}")
    if not evidence_path.exists():
        raise SystemExit(f"EVIDENCE_NOT_FOUND:{evidence_path}")
    report = build_report(session=a.session, audit_path=a.audit, evidence_path=evidence_path)
    print("MODEL:", report["model"])
    print("SESSION:", report["session_date"])
    print("UNRESOLVED:", report["unresolved_count"])
    print("RECOVERABLE:", report["recoverable_count"])
    print("BLOCKED:", report["blocked_count"])
    print()
    for t in report["trades"]:
        signal = _dt(t["signal_bar"]).strftime("%H:%M")
        entry = _dt(t["entry_boundary"]).strftime("%H:%M") if t.get("entry_boundary") else "-"
        exit_ = _dt(t["exit_boundary"]).strftime("%H:%M") if t.get("exit_boundary") else "-"
        print(f"{t['status']:<11} {t['direction']:<7} signal={signal} entry={entry} exit={exit_}")
        if t["status"] == "BLOCKED":
            print("  issue:", t.get("issue"))
    if a.json_output:
        a.json_output.parent.mkdir(parents=True, exist_ok=True)
        a.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("\nJSON:", a.json_output)
    if report["blocked_count"] > 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
