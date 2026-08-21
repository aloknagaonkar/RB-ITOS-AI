from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.execution.trend_automation import (
    TrendAwarePaperAutomationService,
)
from red_bar_lab.services.attribution_pipeline_reconciler import (
    AttributionPipelineReconciler,
)
from red_bar_lab.services.option_participation_atm_window import (
    capture_option_participation_atm_window,
)
from red_bar_lab.services.option_participation_store import persist_option_participation
from red_bar_lab.services.trade_candidate_snapshot_store import persist_trade_candidate_snapshots

IST = ZoneInfo("Asia/Kolkata")


class AttributionAwarePaperAutomationService(
    TrendAwarePaperAutomationService
):
    """Run the existing paper workflow, then publish observational evidence.

    The superclass remains the only execution authority. ATM ± 4 CE/PE option
    participation and attribution reconciliation are post-decision observation
    only and are never consulted by signal admission, order entry or exits.
    Standalone DRI signal refresh and database proxying are retired.
    """

    @staticmethod
    def _dri_runtime_enabled() -> bool:
        """Compatibility hook retained for callers; standalone DRI is retired."""
        return False

    def _refresh_directional_regime_background(self):
        """Return a stable retired-state record without running DRI producers."""
        return {
            "status": "RETIRED",
            "reason": "STANDALONE_DRI_RETIRED",
        }

    def _reconcile_attribution(self):
        settings = self.settings
        runs_root = getattr(settings, "runs_root", None)
        if runs_root is None:
            return {
                "ledgers_seen": 0,
                "candidate_links": 0,
                "opportunity_links": 0,
                "committee_links": 0,
                "trade_entry_links": 0,
                "trade_exit_links": 0,
            }
        raw_database = getattr(self, "_raw_database", self.database)
        return AttributionPipelineReconciler(
            database=raw_database,
            runs_root=runs_root,
        ).reconcile()

    @staticmethod
    def _pcr_view(pcr: float | None, side: str) -> str:
        if pcr is None:
            return "UNAVAILABLE"
        if side == "CE":
            return "SUPPORTIVE" if pcr < 0.95 else "CONTRADICTORY" if pcr > 1.15 else "NEUTRAL"
        if side == "PE":
            return "SUPPORTIVE" if pcr > 1.05 else "CONTRADICTORY" if pcr < 0.85 else "NEUTRAL"
        return "NEUTRAL"

    @staticmethod
    def _rsi_view(rsi: float | None) -> str:
        if rsi is None:
            return "UNAVAILABLE"
        if rsi > 75.0:
            return "OVEREXTENDED"
        if rsi >= 55.0:
            return "SUPPORTIVE"
        if rsi >= 45.0:
            return "NEUTRAL"
        return "CONTRADICTORY"

    def _publish_option_participation(self):
        """Capture and persist ATM ± 4 CE/PE evidence without execution authority."""
        adapter = self.zerodha
        intelligence = getattr(adapter, "intelligence", None)
        underlying_key = getattr(adapter, "underlying_key", None)
        if intelligence is None or not underlying_key:
            return {"status": "UNAVAILABLE", "reason": "MARKET_INTELLIGENCE_UNAVAILABLE", "rows": 0}

        observed_at = datetime.now(IST)
        summary = capture_option_participation_atm_window(
            intelligence=intelligence,
            adapter=adapter,
            underlying_name=self.underlying_name,
            underlying_key=str(underlying_key),
            observed_at=observed_at,
            steps_each_side=4,
        )
        persisted = persist_option_participation(self.settings.database_path, summary)

        selected = []
        if summary.recommended_side in {"CE", "PE"}:
            selected = sorted(
                [row for row in summary.rows if str(row.get("option_type")) == summary.recommended_side],
                key=lambda row: float(row.get("strike_score") or 0.0),
                reverse=True,
            )[:3]
        if selected:
            action = (
                f"BUY {summary.recommended_side} — PAPER OBSERVATION"
                if summary.grade == "STRONG"
                else f"CONSIDER {summary.recommended_side} WITH CAUTION"
                if summary.grade == "MODERATE"
                else "WAIT FOR CONFIRMATION"
            )
            candidates = []
            for row in selected:
                item = dict(row)
                item.update({
                    "candidate_score": row.get("strike_score"),
                    "pcr_oi": summary.pcr_oi,
                    "pcr_status": "AVAILABLE" if summary.pcr_oi is not None else "UNAVAILABLE",
                    "pcr_view": self._pcr_view(summary.pcr_oi, summary.recommended_side),
                    "pcr_snapshot_timestamp": summary.observed_at,
                    "underlying_rsi": summary.underlying_rsi,
                    "rsi_timeframe": "Underlying 5m RSI(14) / Option 1m RSI(14)",
                    "rsi_view": self._rsi_view(row.get("option_rsi")),
                    "rsi_snapshot_timestamp": summary.observed_at,
                    "evidence_grade": summary.grade,
                    "suggested_action": action,
                })
                candidates.append(item)
            persist_trade_candidate_snapshots(
                self.settings.database_path,
                observed_at=summary.observed_at,
                underlying_name=self.underlying_name,
                recommendation_source="INDEPENDENT_MARKET",
                direction=summary.recommended_direction,
                candidates=candidates,
            )
        return {
            "status": "READY" if persisted else "UNAVAILABLE",
            "reason": summary.reason,
            "rows": persisted,
            "ce_score": summary.ce_score,
            "pe_score": summary.pe_score,
            "recommended_side": summary.recommended_side,
            "grade": summary.grade,
        }

    def process_new_signals(self, *args, **kwargs):
        self._last_directional_regime_background_refresh = (
            self._refresh_directional_regime_background()
        )
        result = super().process_new_signals(*args, **kwargs)
        # This runs only after the existing decision path has completed. Any
        # failure is recorded as observational state and cannot fail or alter
        # the stable execution workflow.
        try:
            self._last_option_participation = self._publish_option_participation()
        except Exception as exc:
            self._last_option_participation = {
                "status": "UNAVAILABLE",
                "reason": f"OPTION_PARTICIPATION_CAPTURE_FAILED:{type(exc).__name__}",
                "rows": 0,
            }
        # Attribution reconciliation is historical/observational maintenance.
        # Never execute it synchronously inside the live paper monitor cycle.
        self._last_attribution_reconciliation = {
            "status": "DEFERRED",
            "reason": "INLINE_RECONCILIATION_DISABLED_FOR_LIVE_MONITOR",
        }
        return result
