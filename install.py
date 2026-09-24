#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

TARGET = "backend/market_lab/hilega_directional_live_shadow_v1.py"

HELPERS_OLD = r'''    def _accepted_types(self, decision: DirectionalDecision) -> set[str]:
        return {e.event_type for e in decision.accepted_events}

    def _handle_decision(self, *, now: datetime, bar, decision: DirectionalDecision, audit: bool) -> None:
        accepted = self._accepted_types(decision)
        if audit:
            self._audit(now, "DIRECTIONAL_DECISION", "PROCESSED", {
                "bar_timestamp": bar.ts.isoformat(),
                "trade_owner_before": decision.trade_owner_before,
                "trade_owner_after": decision.trade_owner_after,
                "bullish_state": decision.bullish_state,
                "bearish_state": decision.bearish_state,
                "bullish_armed": decision.bullish_armed,
                "bearish_armed": decision.bearish_armed,
                "accepted_events": [e.event_type for e in decision.accepted_events],
                "suppressed_events": [e.event_type for e in decision.suppressed_events],
                "note": decision.note,
            }, checkpoint=bar.ts)
'''

HELPERS_NEW = r'''    def _accepted_types(self, decision: DirectionalDecision) -> set[str]:
        return {e.event_type for e in decision.accepted_events}

    @staticmethod
    def _directional_decision_payload(bar, decision: DirectionalDecision) -> dict[str, Any]:
        return {
            "bar_timestamp": bar.ts.isoformat(),
            "trade_owner_before": decision.trade_owner_before,
            "trade_owner_after": decision.trade_owner_after,
            "bullish_state": decision.bullish_state,
            "bearish_state": decision.bearish_state,
            "bullish_armed": decision.bullish_armed,
            "bearish_armed": decision.bearish_armed,
            "accepted_events": [e.event_type for e in decision.accepted_events],
            "suppressed_events": [e.event_type for e in decision.suppressed_events],
            "note": decision.note,
        }

    def _audit_directional_decision(
        self,
        *,
        now: datetime,
        bar,
        decision: DirectionalDecision,
        status: str,
        reconstructed: bool = False,
        recovery_source: str | None = None,
    ) -> None:
        payload = self._directional_decision_payload(bar, decision)
        if reconstructed:
            payload["reconstructed"] = True
            payload["recovery_source"] = recovery_source or "BOOTSTRAP_RECOVERY"
        self._audit(now, "DIRECTIONAL_DECISION", status, payload, checkpoint=bar.ts)

    def _existing_directional_decision_checkpoints(self, session_date: date) -> set[str]:
        prefix = session_date.isoformat()
        out: set[str] = set()
        for record in self.step_audit.read_all():
            if record.get("stage") != "DIRECTIONAL_DECISION":
                continue
            checkpoint = record.get("checkpoint")
            payload = record.get("payload") or {}
            candidate = checkpoint or payload.get("bar_timestamp")
            if isinstance(candidate, str) and candidate.startswith(prefix):
                out.add(candidate)
        return out

    def _handle_decision(self, *, now: datetime, bar, decision: DirectionalDecision, audit: bool) -> None:
        accepted = self._accepted_types(decision)
        if audit:
            self._audit_directional_decision(
                now=now,
                bar=bar,
                decision=decision,
                status="PROCESSED",
            )
'''

BOOTSTRAP_OLD = r'''        current = self.sources.nifty_intraday_1m(now=now)
        completed_label = latest_completed_5m_label(now)
        completed_current = completed_intraday_1m_for_label(current, completed_label)
        current_bars = aggregate_exact_5m(completed_current, session_date)
        for bar in current_bars:
            if bar.ts <= completed_label:
                decision = self.directional.on_bar(bar)
                self._handle_decision(now=now, bar=bar, decision=decision, audit=False)
                self._last_bar_ts = bar.ts
                bars_replayed += 1

        self._bootstrapped_date = session_date
'''

BOOTSTRAP_NEW = r'''        current = self.sources.nifty_intraday_1m(now=now)
        completed_label = latest_completed_5m_label(now)
        completed_current = completed_intraday_1m_for_label(current, completed_label)
        current_bars = aggregate_exact_5m(completed_current, session_date)

        existing_directional = self._existing_directional_decision_checkpoints(session_date)
        recovered_checkpoints: list[str] = []
        for bar in current_bars:
            if bar.ts <= completed_label:
                decision = self.directional.on_bar(bar)
                self._handle_decision(now=now, bar=bar, decision=decision, audit=False)

                checkpoint = bar.ts.isoformat()
                if checkpoint not in existing_directional:
                    self._audit_directional_decision(
                        now=now,
                        bar=bar,
                        decision=decision,
                        status="RECOVERED",
                        reconstructed=True,
                        recovery_source="BOOTSTRAP_RECOVERY",
                    )
                    existing_directional.add(checkpoint)
                    recovered_checkpoints.append(checkpoint)

                self._last_bar_ts = bar.ts
                bars_replayed += 1

        self._bootstrapped_date = session_date
'''

BOOTSTRAP_AUDIT_OLD = r'''            "pe_shadow_status": self.pe_shadow.snapshot.status if self.pe_shadow.snapshot else None,
        })
        return {"status": "BOOTSTRAPPED", "session_date": session_date.isoformat(), "trade_owner": self.directional.trade_owner}
'''

BOOTSTRAP_AUDIT_NEW = r'''            "pe_shadow_status": self.pe_shadow.snapshot.status if self.pe_shadow.snapshot else None,
            "recovery_source": "BOOTSTRAP_RECOVERY",
            "reconstructed": True,
            "recovered_checkpoint_count": len(recovered_checkpoints),
            "recovered_checkpoints": recovered_checkpoints,
        })
        return {
            "status": "BOOTSTRAPPED",
            "session_date": session_date.isoformat(),
            "trade_owner": self.directional.trade_owner,
            "recovered_checkpoint_count": len(recovered_checkpoints),
        }
'''

def patch_source(src: str) -> str:
    for label, needle in [
        ("decision helper block", HELPERS_OLD),
        ("bootstrap current-session block", BOOTSTRAP_OLD),
        ("bootstrap audit block", BOOTSTRAP_AUDIT_OLD),
    ]:
        if needle not in src:
            raise SystemExit(f"BLOCKED: expected {label} not found; source has drifted")
    src = src.replace(HELPERS_OLD, HELPERS_NEW, 1)
    src = src.replace(BOOTSTRAP_OLD, BOOTSTRAP_NEW, 1)
    src = src.replace(BOOTSTRAP_AUDIT_OLD, BOOTSTRAP_AUDIT_NEW, 1)
    return src

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = p.parse_args()

    repo = Path(a.repo).resolve()
    target = repo / TARGET
    if not target.is_file():
        raise SystemExit(f"BLOCKED: missing {target}")

    current = target.read_text()
    patched = patch_source(current)

    print("READY")
    print("  - Phase 6.3B automatic current-day directional timeline recovery")
    print("  - same HilegaDirectionalCoordinatorV1 bootstrap replay")
    print("  - writes only missing DIRECTIONAL_DECISION checkpoints")
    print("  - recovered rows marked RECOVERED/reconstructed/BOOTSTRAP_RECOVERY")
    print("  - existing live checkpoints are not duplicated")
    print("  - no strategy/UI/execution changes")

    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = repo / ".hilega-directional-bootstrap-recovery-phase6-3b-backup" / stamp
    backup = backup_root / TARGET
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    target.write_text(patched)

    test_src = Path(__file__).resolve().parent / "files/tests/test_hilega_directional_bootstrap_recovery_v1.py"
    test_dst = repo / "tests/test_hilega_directional_bootstrap_recovery_v1.py"
    test_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(test_src, test_dst)

    print("APPLY PASS")
    print("Backup root:", backup_root)
    print("Do not restart Hilega worker until tests pass.")

if __name__ == "__main__":
    main()
