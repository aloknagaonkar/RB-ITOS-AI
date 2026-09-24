#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil
from datetime import datetime, timezone

REL = Path("backend/market_lab/hilega_milega_live_shadow_v1.py")

OLD = r"""        current = self.sources.nifty_intraday_1m(now=now)
        completed_label = latest_completed_5m_label(now)
        completed_current = completed_intraday_1m_for_label(current, completed_label)
        current_bars = aggregate_exact_5m(completed_current, session_date)
        for bar in current_bars:
            if bar.ts <= completed_label:
                self.strategy.on_bar(bar)
                self._last_bar_ts = bar.ts
                bars_replayed += 1

        # Bootstrap history is intentionally not written into the live audit.
        self.strategy.audit_store = self.step_audit
"""

NEW = r"""        current = self.sources.nifty_intraday_1m(now=now)
        completed_label = latest_completed_5m_label(now)
        completed_current = completed_intraday_1m_for_label(current, completed_label)
        current_bars = aggregate_exact_5m(completed_current, session_date)

        # Historical warmup remains silent, but current-session bootstrap bars
        # are captured in-memory so a restart cannot silently remove an already
        # completed 5m checkpoint from the append-only live audit.
        class _BootstrapAuditCollector:
            def __init__(self):
                self.rows = []
            def append(self, *, event_time, checkpoint, stage, status, payload):
                self.rows.append({
                    "event_time": event_time,
                    "checkpoint": checkpoint,
                    "stage": stage,
                    "status": status,
                    "payload": dict(payload or {}),
                })

        collector = _BootstrapAuditCollector()
        self.strategy.audit_store = collector
        for bar in current_bars:
            if bar.ts <= completed_label:
                self.strategy.on_bar(bar)
                self._last_bar_ts = bar.ts
                bars_replayed += 1

        # Recover only checkpoints that are absent from the canonical audit.
        # Existing checkpoints are never duplicated or rewritten.
        existing_rows = self.step_audit.read_all()
        existing_decision_checkpoints = {
            str(r.get("checkpoint"))
            for r in existing_rows
            if r.get("stage") == "STRATEGY_DECISION"
            and str(r.get("checkpoint") or "").startswith(session_date.isoformat())
        }
        recovered_checkpoints = []
        by_checkpoint = {}
        for row in collector.rows:
            cp = row.get("checkpoint")
            if cp is None:
                continue
            cp_iso = cp.isoformat() if hasattr(cp, "isoformat") else str(cp)
            by_checkpoint.setdefault(cp_iso, []).append(row)

        for cp_iso in sorted(by_checkpoint):
            if cp_iso in existing_decision_checkpoints:
                continue
            recovered_checkpoints.append(cp_iso)
            for row in by_checkpoint[cp_iso]:
                payload = {
                    **(row.get("payload") or {}),
                    "bootstrap_recovered": True,
                    "recovery_source": "CURRENT_SESSION_BOOTSTRAP_REPLAY",
                    "recovered_at": now.isoformat(),
                }
                self.step_audit.append(
                    event_time=row["event_time"],
                    checkpoint=row["checkpoint"],
                    stage=row["stage"],
                    status=row["status"],
                    payload=payload,
                )
            self.step_audit.append(
                event_time=now,
                checkpoint=datetime.fromisoformat(cp_iso),
                stage="BOOTSTRAP_RECOVERED_CHECKPOINT",
                status="RECOVERED",
                payload={
                    "checkpoint": cp_iso,
                    "recovery_source": "CURRENT_SESSION_BOOTSTRAP_REPLAY",
                    "recorded_live_checkpoint_present": False,
                },
            )

        # Normal future live processing resumes on the real append-only audit.
        self.strategy.audit_store = self.step_audit
"""

OLD_BOOT = r"""            "last_completed_bar": self._last_bar_ts.isoformat() if self._last_bar_ts else None,
            "reconstructed_state": self.strategy.session.name,
        })"""

NEW_BOOT = r"""            "last_completed_bar": self._last_bar_ts.isoformat() if self._last_bar_ts else None,
            "reconstructed_state": self.strategy.session.name,
            "recovered_checkpoints": recovered_checkpoints,
            "recovered_checkpoint_count": len(recovered_checkpoints),
        })"""

def main():
    ap=argparse.ArgumentParser(description="Recover missing current-session Hilega checkpoints during bootstrap")
    ap.add_argument("--repo", required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a=ap.parse_args()

    repo=Path(a.repo).resolve()
    p=repo/REL
    if not p.is_file():
        print("BLOCKED: missing", REL)
        raise SystemExit(2)

    text=p.read_text(encoding="utf-8")
    if NEW in text and NEW_BOOT in text:
        print("ALREADY_PATCHED:", REL)
        return
    if OLD not in text or OLD_BOOT not in text:
        print("BLOCKED: expected bootstrap source blocks were not found exactly.")
        print("No file changed.")
        raise SystemExit(2)

    print("READY:", REL)
    print("  - historical warmup remains silent")
    print("  - current-session replay is captured in-memory")
    print("  - only missing STRATEGY_DECISION checkpoints are appended")
    print("  - recovered rows keep actual replayed OHLC/RSI/EMA/WMA/events")
    print("  - existing audit rows are never rewritten or duplicated")
    print("  - each recovered checkpoint gets BOOTSTRAP_RECOVERED_CHECKPOINT evidence")
    print("  - strategy rules and order safety are unchanged")
    if a.check:
        print("CHECK PASS")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-bootstrap-recovery-backup"/stamp/REL
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, backup)

    patched=text.replace(OLD, NEW, 1).replace(OLD_BOOT, NEW_BOOT, 1)
    p.write_text(patched, encoding="utf-8")

    verify=p.read_text(encoding="utf-8")
    if NEW not in verify or NEW_BOOT not in verify:
        shutil.copy2(backup,p)
        print("BLOCKED: post-write verification failed; original restored.")
        raise SystemExit(2)

    print("APPLY PASS")
    print("Backup:",backup)
    print("Important: this changes the live worker coordinator. Apply after market or restart the live-shadow worker only when you intentionally choose to.")

if __name__=="__main__":
    main()
