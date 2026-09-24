#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

BACKEND = Path("backend/market_lab/hilega_milega_audit_report_v1.py")
FRONTEND = Path("frontend/src/hilegaDecisionTable.tsx")

BACKEND_OLD_1 = r"""
    lifecycle_updates = [r for r in option_rows if r.get("stage") == "OPTION_SHADOW_LIFECYCLE_UPDATE"]
    lifecycle_exit = next((r for r in reversed(option_rows) if r.get("stage") in {"OPTION_SHADOW_LIFECYCLE_EXIT", "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY"}), None)

    conditions = {
"""

BACKEND_NEW_1 = r"""
    lifecycle_updates = [r for r in option_rows if r.get("stage") == "OPTION_SHADOW_LIFECYCLE_UPDATE"]
    lifecycle_exit = next((r for r in reversed(option_rows) if r.get("stage") in {"OPTION_SHADOW_LIFECYCLE_EXIT", "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY"}), None)

    # Projection-only restart recovery. If a lifecycle record proves that a
    # bullish entry existed at signal_bar but the append-only live journal has
    # no canonical strategy decision for that checkpoint (for example because
    # the process restarted across the boundary), expose a clearly marked
    # reconstructed entry to read-only UIs. Never mutate or backfill raw audit.
    lifecycle_payload = (lifecycle_start or {}).get("payload") or {}
    reconstructed_entry = (
        decision is None
        and result is None
        and lifecycle_start is not None
        and lifecycle_payload.get("signal_bar") == checkpoint
        and bool(lifecycle_payload.get("source"))
    )
    reconstructed_source = lifecycle_payload.get("source") if reconstructed_entry else None
    reconstructed_route = None
    if reconstructed_source:
        source_upper = str(reconstructed_source).upper()
        if "ROUTE_A" in source_upper:
            reconstructed_route = "ROUTE_A"
        elif "ROUTE_B" in source_upper:
            reconstructed_route = "ROUTE_B"
        elif "OPENING" in source_upper:
            reconstructed_route = "OPENING_PATH"

    projected_transitions = _transition_summary(strategy_rows)
    if reconstructed_entry:
        projected_transitions.append({
            "event_type": "ENTRY_RECONSTRUCTED_FROM_OPTION_LIFECYCLE",
            "event_time": checkpoint,
            "price": lifecycle_payload.get("signal_spot"),
            "source": reconstructed_source,
            "state_before": None,
            "state_after": "BULLISH_ACTIVE",
            "exit_reason": None,
            "points": None,
            "details": {
                "projection": "RECONSTRUCTED_ENTRY",
                "evidence_origin": lifecycle_start.get("stage"),
                "evidence_event_time": lifecycle_start.get("event_time"),
                "recorded_live_strategy_transition": False,
            },
        })

    conditions = {
"""

BACKEND_OLD_2 = r"""
        "strategy": {
            "strategy_id": dp.get("strategy_id") or rp.get("strategy_id") or ip.get("strategy_id"),
            "strategy_version": dp.get("strategy_version") or rp.get("strategy_version") or ip.get("strategy_version"),
            "state_before": dp.get("state_before"),
            "state_after": rp.get("state_after"),
            "selected_route": rp.get("selected_route"),
            "route_b_suppressed_by_route_a_priority": rp.get("route_b_suppressed_by_route_a_priority"),
            "events_emitted": rp.get("events_emitted") or [],
            "note": rp.get("note"),
        },
"""

BACKEND_NEW_2 = r"""
        "strategy": {
            "strategy_id": dp.get("strategy_id") or rp.get("strategy_id") or ip.get("strategy_id") or lifecycle_payload.get("strategy_id"),
            "strategy_version": dp.get("strategy_version") or rp.get("strategy_version") or ip.get("strategy_version") or lifecycle_payload.get("strategy_version"),
            "state_before": dp.get("state_before"),
            "state_after": rp.get("state_after") or ("BULLISH_ACTIVE" if reconstructed_entry else None),
            "selected_route": rp.get("selected_route") or reconstructed_route,
            "route_b_suppressed_by_route_a_priority": rp.get("route_b_suppressed_by_route_a_priority"),
            "events_emitted": rp.get("events_emitted") or (["ENTRY_RECONSTRUCTED_FROM_OPTION_LIFECYCLE"] if reconstructed_entry else []),
            "note": rp.get("note") or ("RECONSTRUCTED_FROM_OPTION_LIFECYCLE; canonical live strategy checkpoint was not recorded" if reconstructed_entry else None),
        },
"""

BACKEND_OLD_3 = r"""
        "transitions": _transition_summary(strategy_rows),
        "option_candidate": None if candidate is None else {
"""

BACKEND_NEW_3 = r"""
        "transitions": projected_transitions,
        "projection": None if not reconstructed_entry else {
            "kind": "RECONSTRUCTED_ENTRY",
            "source_stage": lifecycle_start.get("stage"),
            "source_event_time": lifecycle_start.get("event_time"),
            "raw_strategy_checkpoint_present": False,
        },
        "option_candidate": None if candidate is None else {
"""

BACKEND_OLD_4 = r"""
def build_audit_index(rows: Iterable[dict[str, Any]], *, mode: str, chain_ok: bool | None = None, chain_issue: str | None = None) -> list[dict[str, Any]]:
    all_rows = list(rows)
    checkpoints = []
    seen = set()
    for r in all_rows:
        cp = r.get("checkpoint")
        if cp and cp not in seen and r.get("stage") == "STRATEGY_DECISION":
            seen.add(cp)
            checkpoints.append(cp)
    return [build_detailed_audit_report(all_rows, checkpoint=cp, mode=mode, chain_ok=chain_ok, chain_issue=chain_issue) for cp in checkpoints]
"""

BACKEND_NEW_4 = r"""
def build_audit_index(rows: Iterable[dict[str, Any]], *, mode: str, chain_ok: bool | None = None, chain_issue: str | None = None) -> list[dict[str, Any]]:
    all_rows = list(rows)
    checkpoints = []
    seen = set()
    for r in all_rows:
        cp = r.get("checkpoint")
        if cp and cp not in seen and r.get("stage") == "STRATEGY_DECISION":
            seen.add(cp)
            checkpoints.append(cp)

    # A restart can leave a real signal_bar represented only by the restored
    # option lifecycle. Add that checkpoint to the read-only projection without
    # altering append-only evidence. A later canonical strategy decision wins
    # automatically because it is already in `seen`.
    recovery_stages = {
        "OPTION_SHADOW_LIFECYCLE_START",
        "OPTION_SHADOW_LIFECYCLE_RESTORE",
        "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY",
    }
    for r in all_rows:
        if r.get("stage") not in recovery_stages:
            continue
        p = r.get("payload") or {}
        cp = p.get("signal_bar")
        if (
            cp
            and cp not in seen
            and p.get("source")
            and (str(p.get("status") or r.get("status") or "").upper() in {"ACTIVE", "INCOMPLETE"})
        ):
            seen.add(cp)
            checkpoints.append(cp)

    return [build_detailed_audit_report(all_rows, checkpoint=cp, mode=mode, chain_ok=chain_ok, chain_issue=chain_issue) for cp in checkpoints]
"""

FRONTEND_OLD_1 = r"""
  option_lifecycle?: Record<string, any> | null
  audit_integrity?: Record<string, any>
"""

FRONTEND_NEW_1 = r"""
  option_lifecycle?: Record<string, any> | null
  projection?: Record<string, any> | null
  audit_integrity?: Record<string, any>
"""

FRONTEND_OLD_2 = r"""
export function shortRuleText(r:HilegaAudit,kind:DisplayKind,lifecycleIssue?:string|null):string {
  const path=pathText(r).toUpperCase()
  const at=clock(r.checkpoint)
  if(kind==='ENTRY'){
    if(path.includes('OPENING'))return 'ENTRY · OPEN 09:15 ALIGN → 09:20 RSI>WMA → 09:25 RSI>WMA'
"""

FRONTEND_NEW_2 = r"""
export function shortRuleText(r:HilegaAudit,kind:DisplayKind,lifecycleIssue?:string|null):string {
  const path=pathText(r).toUpperCase()
  const at=clock(r.checkpoint)
  if(kind==='ENTRY'){
    if(String(r.projection?.kind??'')==='RECONSTRUCTED_ENTRY'){
      if(path.includes('ROUTE A'))return 'ENTRY · RECONSTRUCTED · ROUTE A'
      if(path.includes('ROUTE B'))return 'ENTRY · RECONSTRUCTED · ROUTE B'
      if(path.includes('OPENING'))return 'ENTRY · RECONSTRUCTED · OPENING PATH'
      return 'ENTRY · RECONSTRUCTED FROM RECORDED LIFECYCLE'
    }
    if(path.includes('OPENING'))return 'ENTRY · OPEN 09:15 ALIGN → 09:20 RSI>WMA → 09:25 RSI>WMA'
"""

def patch_exact(text, old, new, label):
    if new in text:
        return text, False
    if old not in text:
        raise RuntimeError(f"BLOCKED: expected block not found: {label}")
    return text.replace(old, new, 1), True

def main():
    ap = argparse.ArgumentParser(description="Hilega restart-gap reconstructed entry projection")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    bp = repo / BACKEND
    fp = repo / FRONTEND
    if not bp.is_file() or not fp.is_file():
        print("BLOCKED: required source file missing.")
        raise SystemExit(2)

    try:
        bt = bp.read_text(encoding="utf-8")
        ft = fp.read_text(encoding="utf-8")
        bnew, b1 = patch_exact(bt, BACKEND_OLD_1, BACKEND_NEW_1, "backend lifecycle recovery")
        bnew, b2 = patch_exact(bnew, BACKEND_OLD_2, BACKEND_NEW_2, "backend strategy projection")
        bnew, b3 = patch_exact(bnew, BACKEND_OLD_3, BACKEND_NEW_3, "backend transition/projection output")
        bnew, b4 = patch_exact(bnew, BACKEND_OLD_4, BACKEND_NEW_4, "backend index recovery checkpoint")
        fnew, f1 = patch_exact(ft, FRONTEND_OLD_1, FRONTEND_NEW_1, "frontend projection type")
        fnew, f2 = patch_exact(fnew, FRONTEND_OLD_2, FRONTEND_NEW_2, "frontend reconstructed label")
    except RuntimeError as exc:
        print(exc)
        print("No files changed.")
        raise SystemExit(2)

    changed = any([b1,b2,b3,b4,f1,f2])
    if not changed:
        print("ALREADY_PATCHED")
        return

    print("READY")
    print("  - raw step-audit.jsonl remains append-only and untouched")
    print("  - missing signal checkpoint is projected only when option lifecycle proves signal_bar/source")
    print("  - projected row is explicitly marked RECONSTRUCTED_ENTRY")
    print("  - no RSI/EMA/WMA or candle OHLC is fabricated")
    print("  - route is recovered only from recorded lifecycle source")
    print("  - canonical strategy checkpoints always take precedence")
    if args.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo / ".hilega-bootstrap-entry-projection-backup" / stamp
    for rel, src in [(BACKEND,bp),(FRONTEND,fp)]:
        dst = backup_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    bp.write_text(bnew, encoding="utf-8")
    fp.write_text(fnew, encoding="utf-8")
    print("APPLY PASS")
    print("Backup:", backup_root)
    print("Run pytest + frontend build. Restart only the API; do not restart the Hilega worker.")

if __name__ == "__main__":
    main()
