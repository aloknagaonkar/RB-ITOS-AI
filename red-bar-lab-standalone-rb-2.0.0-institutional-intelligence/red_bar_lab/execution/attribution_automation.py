from __future__ import annotations

from red_bar_lab.execution.trend_automation import (
    TrendAwarePaperAutomationService,
)
from red_bar_lab.services.attribution_pipeline_reconciler import (
    AttributionPipelineReconciler,
)
from red_bar_lab.execution.directional_regime_background import (
    DirectionalRegimeBackgroundCycle,
)
from red_bar_lab.execution.directional_regime_native_signal import (
    DirectionalNativeSignalDatabaseProxy,
)
from red_bar_lab.execution.paper_strategy_authority import (
    PaperStrategyAuthority,
)


class AttributionAwarePaperAutomationService(
    TrendAwarePaperAutomationService
):
    """Run the existing paper workflow, then reconcile v4.3 attribution.

    The superclass remains the only execution authority. Reconciliation is
    database/file observation after the existing process has completed.
    """

    @staticmethod
    def _dri_runtime_enabled() -> bool:
        return PaperStrategyAuthority.from_env().dri_strategy_enabled

    def _refresh_directional_regime_background(self):
        if not self._dri_runtime_enabled():
            return {
                "status": "DISABLED",
                "reason": "DRI_STRATEGY_DISABLED",
            }
        runs_root = getattr(self.settings, "runs_root", None)
        if runs_root is None:
            return {
                "status": "UNAVAILABLE",
                "reason": "RUNS_ROOT_UNAVAILABLE",
            }
        try:
            result = DirectionalRegimeBackgroundCycle(
                adapter=self.zerodha,
                runs_root=runs_root,
            ).run()
            return result.as_record()
        except Exception as exc:
            return {
                "status": "UNAVAILABLE",
                "reason": (
                    f"BACKGROUND_REFRESH_FAILED:"
                    f"{type(exc).__name__}:{exc}"
                ),
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
        dri_enabled = self._dri_runtime_enabled()
        self._last_directional_regime_background_refresh = (
            self._refresh_directional_regime_background()
        )
        original_database = self.database
        runs_root = getattr(self.settings, "runs_root", None)
        if dri_enabled and runs_root is not None:
            self.database = DirectionalNativeSignalDatabaseProxy(
                original_database,
                runs_root=runs_root,
                merge_window_minutes=10,
                enable_reference_signals=None,
            )
        try:
            result = super().process_new_signals(*args, **kwargs)
        finally:
            self.database = original_database
        self._last_attribution_reconciliation = (
            self._reconcile_attribution()
        )
        return result
