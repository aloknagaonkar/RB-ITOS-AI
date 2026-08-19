from __future__ import annotations

from red_bar_lab.execution.trend_automation import (
    TrendAwarePaperAutomationService,
)
from red_bar_lab.services.attribution_pipeline_reconciler import (
    AttributionPipelineReconciler,
)


class AttributionAwarePaperAutomationService(
    TrendAwarePaperAutomationService
):
    """Run the existing paper workflow, then reconcile v4.3 attribution.

    The superclass remains the only execution authority. Reconciliation is
    database/file observation after the existing process has completed.
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

    def process_new_signals(self, *args, **kwargs):
        self._last_directional_regime_background_refresh = (
            self._refresh_directional_regime_background()
        )
        result = super().process_new_signals(*args, **kwargs)
        # Attribution reconciliation is historical/observational maintenance.
        # Never execute it synchronously inside the live paper monitor cycle.
        self._last_attribution_reconciliation = {
            "status": "DEFERRED",
            "reason": "INLINE_RECONCILIATION_DISABLED_FOR_LIVE_MONITOR",
        }
        return result
