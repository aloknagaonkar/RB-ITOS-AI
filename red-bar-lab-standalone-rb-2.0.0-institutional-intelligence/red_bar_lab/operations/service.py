from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import os

import pandas as pd

from red_bar_lab.collector.service import market_session_phase
from red_bar_lab.features.store import RedBarFeatureStore

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class HealthItem:
    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class OperationsSnapshot:
    health_score: int
    platform_health: tuple[HealthItem, ...]
    market: dict[str, object]
    pipeline: dict[str, object]
    ai_readiness: dict[str, object]
    data_quality: dict[str, object]
    performance: dict[str, object]
    timeline: tuple[dict[str, object], ...]


def _state(ok: bool, warning: bool = False) -> str:
    if ok:
        return "HEALTHY"
    return "WARNING" if warning else "CRITICAL"


def _safe_ts(value):
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("Asia/Kolkata")
        else:
            ts = ts.tz_convert("Asia/Kolkata")
        return ts
    except Exception:
        return None


def _size_mb(path: Path) -> float:
    try:
        return round(path.stat().st_size / (1024 * 1024), 2)
    except OSError:
        return 0.0


def _tree_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return round(total / (1024 * 1024), 2)


def _signal_id(row: dict[str, object]) -> str:
    return str(row.get("signal_id") or "")


def _readiness_signal_scope(
    signals: list[dict[str, object]],
) -> tuple[list[dict[str, object]], str]:
    """Prefer current Red Bar V2 signals without hiding legacy-only sessions."""
    v2_signals = [row for row in signals if _signal_id(row).startswith("RBV2-")]
    if v2_signals:
        return v2_signals, "RED_BAR_V2"
    return signals, "ALL_SIGNALS"


class RedBarOperationsCenterService:
    def __init__(self, database, settings):
        self.database = database
        self.settings = settings
        self.feature_store = RedBarFeatureStore(database)

    def snapshot(
        self,
        *,
        instrument_key: str,
        trading_date: str | None = None,
        now: datetime | None = None,
        token_present: bool = False,
    ) -> OperationsSnapshot:
        now = (now or datetime.now(IST)).astimezone(IST)
        trading_date = trading_date or now.date().isoformat()

        db_health = self.database.health()
        collector = self.database.read_collector_status()
        pipeline_status = self.database.read_pipeline_run_status(
            instrument_key, trading_date
        )
        eod = self.database.read_eod_pipeline_validation(
            instrument_key, trading_date
        )

        all_signals = self.database.read_signal_attempts(
            instrument_key, trading_date
        )
        signals, readiness_scope = _readiness_signal_scope(all_signals)
        confirmed = [
            row for row in signals
            if row.get("confirmation_timestamp")
        ]
        active = [row for row in signals if row.get("state") == "ACTIVE"]
        failed = [
            row for row in signals
            if row.get("state") in {"FAILED", "TIMEOUT"}
        ]
        readiness_ids = {
            _signal_id(row) for row in confirmed if _signal_id(row)
        }

        market_rows = self.database.read_market_context_snapshots(
            instrument_key, trading_date, trading_date
        )
        volume_rows = self.database.read_volume_structure_snapshots(
            instrument_key, trading_date, trading_date
        )
        option_rows = self.database.read_option_context_snapshots(
            instrument_key, trading_date, trading_date
        )

        if readiness_ids:
            market_rows = [
                row for row in market_rows
                if _signal_id(row) in readiness_ids
            ]
            volume_rows = [
                row for row in volume_rows
                if _signal_id(row) in readiness_ids
            ]
            option_by_id = {
                _signal_id(row): row
                for row in option_rows
                if _signal_id(row) in readiness_ids
            }
            # Older rows could have been persisted with trading_date='None'.
            # Resolve those by signal id so valid aligned context remains visible.
            for signal_id in readiness_ids - set(option_by_id):
                row = self.database.read_option_context_by_signal(signal_id)
                if row:
                    option_by_id[signal_id] = row
            option_rows = list(option_by_id.values())

        option_aligned = [
            row for row in option_rows if bool(row.get("entry_aligned"))
        ]

        snapshots = self.database.read_option_chain_history(
            instrument_key, trading_date, trading_date, limit=1000
        )
        online_snapshots = [
            row for row in snapshots
            if row.get("collector_mode") == "ONLINE"
        ]
        eod_snapshots = [
            row for row in snapshots
            if row.get("collector_mode") == "EOD"
        ]

        pipeline_rows = self.database.read_signal_pipeline_status_range(
            instrument_key, trading_date, trading_date
        )
        if readiness_ids:
            pipeline_rows = [
                row for row in pipeline_rows
                if _signal_id(row) in readiness_ids
            ]
        core_ready = sum(
            int(bool(row.get("core_eligible"))) for row in pipeline_rows
        )
        hybrid_ready = sum(
            int(bool(row.get("hybrid_eligible"))) for row in pipeline_rows
        )

        historical_signals = self.database.read_signal_attempts_range(
            instrument_key, "2000-01-01", trading_date
        )
        historical_options = self.database.read_historical_option_backfill_range(
            instrument_key, "2000-01-01", trading_date
        )
        feature_rows = self.feature_store.rows_for_range(
            instrument_key, "2000-01-01", trading_date
        )

        paper_rows = self.database.read_paper_trade_outcomes_range(
            instrument_key, "2000-01-01", trading_date
        )
        paper_today = self.database.read_paper_trade_outcomes(
            instrument_key, trading_date
        )
        completed_trade_ids = {
            str(row.get("trade_id"))
            for row in paper_rows
            if row.get("trade_id")
            and row.get("points") is not None
            and row.get("exit_reason") != "NOT_EVALUABLE"
        }

        training_samples = len(completed_trade_ids)
        target_samples = 1000
        readiness_pct = min(
            100.0,
            training_samples / target_samples * 100.0
            if target_samples else 0.0,
        )

        last_snapshot = None
        if snapshots:
            last_snapshot = max(
                (
                    _safe_ts(row.get("snapshot_timestamp"))
                    for row in snapshots
                ),
                default=None,
            )

        collector_ts = (
            _safe_ts(collector.get("updated_at"))
            if collector else None
        )
        collector_age = (
            (now - collector_ts.to_pydatetime()).total_seconds()
            if collector_ts is not None else None
        )

        phase = market_session_phase(now)
        collector_expected_live = phase == "OPEN"
        collector_healthy = bool(collector) and str(
            collector.get("status")
        ) not in {"ERROR", "CRITICAL"}
        if collector_expected_live and collector_age is not None:
            collector_healthy = collector_healthy and collector_age <= 180

        pipeline_healthy = (
            pipeline_status is None
            or str(pipeline_status.get("status")) in {
                "HEALTHY", "WAITING"
            }
        )

        core_complete = (
            len(confirmed) == 0 or core_ready == len(confirmed)
        )
        options_complete = (
            len(confirmed) == 0 or hybrid_ready == len(confirmed)
        )

        platform_health = (
            HealthItem(
                "Database",
                _state(bool(db_health.get("ok"))),
                str(db_health.get("path") or ""),
            ),
            HealthItem(
                "Collector",
                _state(
                    collector_healthy,
                    warning=not collector_expected_live,
                ),
                (
                    str(collector.get("message") or "")
                    if collector else "Collector has not reported yet."
                ),
            ),
            HealthItem(
                "Pipeline",
                _state(pipeline_healthy, warning=pipeline_status is None),
                (
                    str(pipeline_status.get("message") or "")
                    if pipeline_status
                    else "Waiting for first confirmed signal."
                ),
            ),
            HealthItem(
                "Feature Store",
                _state(core_complete, warning=not core_complete),
                f"CORE {core_ready}/{len(confirmed)}",
            ),
            HealthItem(
                "Options Context",
                _state(options_complete, warning=not options_complete),
                f"HYBRID {hybrid_ready}/{len(confirmed)}",
            ),
            HealthItem(
                "Upstox Token",
                _state(token_present, warning=not token_present),
                "Configured" if token_present else "Token not present in UI/session.",
            ),
        )

        scores = {
            "Database": 100 if db_health.get("ok") else 0,
            "Collector": 100 if collector_healthy else (
                80 if not collector_expected_live else 30
            ),
            "Pipeline": 100 if pipeline_healthy else 40,
            "Feature Store": (
                100 if core_complete else (
                    core_ready / len(confirmed) * 100
                    if confirmed else 100
                )
            ),
            "Data Quality": (
                100 if not confirmed else (
                    (core_ready + hybrid_ready)
                    / (2 * len(confirmed))
                    * 100
                )
            ),
        }
        health_score = int(
            round(sum(scores.values()) / len(scores))
        )

        market = {
            "phase": phase,
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "collector_mode": (
                collector.get("collector_mode") if collector else "—"
            ),
            "collector_status": (
                collector.get("status") if collector else "NOT STARTED"
            ),
            "last_snapshot": (
                last_snapshot.strftime("%H:%M:%S")
                if last_snapshot is not None else "—"
            ),
            "snapshots_today": len(snapshots),
            "online_snapshots_today": len(online_snapshots),
            "eod_snapshots_today": len(eod_snapshots),
            "current_expiry": (
                snapshots[0].get("option_expiry")
                if snapshots else None
            ),
        }

        pipeline = {
            "signals_today": len(signals),
            "confirmed_signals": len(confirmed),
            "active_signals": len(active),
            "failed_signals": len(failed),
            "market_context": len(market_rows),
            "volume_structure": len(volume_rows),
            "options_context": len(option_aligned),
            "core_ready": core_ready,
            "hybrid_ready": hybrid_ready,
            "readiness_scope": readiness_scope,
            "pipeline_status": (
                pipeline_status.get("status")
                if pipeline_status else "WAITING"
            ),
            "eod_status": (
                eod.get("status") if eod else "WAITING"
            ),
        }

        ai_readiness = {
            "training_samples": training_samples,
            "target_samples": target_samples,
            "readiness_pct": round(readiness_pct, 1),
            "historical_signals": len(historical_signals),
            "feature_store_rows": len(feature_rows),
            "historical_options_days": len(historical_options),
            "core_samples_today": core_ready,
            "hybrid_samples_today": hybrid_ready,
            "status": (
                "READY"
                if training_samples >= target_samples
                else "BUILDING DATASET"
            ),
        }

        signal_ids = readiness_ids
        market_ids = {
            _signal_id(row) for row in market_rows if _signal_id(row)
        }
        volume_ids = {
            _signal_id(row) for row in volume_rows if _signal_id(row)
        }
        option_ids = {
            _signal_id(row) for row in option_aligned if _signal_id(row)
        }

        duplicates = max(
            0,
            len(snapshots)
            - len({
                str(row.get("snapshot_key"))
                for row in snapshots
                if row.get("snapshot_key")
            }),
        )
        data_quality = {
            "duplicate_snapshots": duplicates,
            "missing_market_context": len(signal_ids - market_ids),
            "missing_volume_structure": len(signal_ids - volume_ids),
            "missing_options_context": len(signal_ids - option_ids),
            "incomplete_core": max(0, len(signal_ids) - core_ready),
            "incomplete_hybrid": max(0, len(signal_ids) - hybrid_ready),
            "readiness_scope": readiness_scope,
            "pipeline_errors": (
                0
                if pipeline_status is None
                or str(pipeline_status.get("status")) != "PARTIAL"
                else 1
            ),
        }

        process_memory_mb = None
        try:
            import psutil
            process_memory_mb = round(
                psutil.Process(os.getpid()).memory_info().rss
                / (1024 * 1024),
                2,
            )
        except Exception:
            process_memory_mb = None

        db_path = Path(self.settings.database_path)
        performance = {
            "database_size_mb": _size_mb(db_path),
            "artifacts_size_mb": _tree_size_mb(
                Path(self.settings.artifacts_root)
            ),
            "feature_store_rows": len(feature_rows),
            "historical_options_days": len(historical_options),
            "option_snapshots_today": len(snapshots),
            "collector_heartbeat_age_sec": (
                round(collector_age, 1)
                if collector_age is not None else None
            ),
            "ui_process_memory_mb": process_memory_mb,
        }

        timeline = self._timeline(
            signals=signals,
            snapshots=snapshots,
            paper_trades=paper_today,
            pipeline_status=pipeline_status,
            eod=eod,
        )

        return OperationsSnapshot(
            health_score=health_score,
            platform_health=platform_health,
            market=market,
            pipeline=pipeline,
            ai_readiness=ai_readiness,
            data_quality=data_quality,
            performance=performance,
            timeline=tuple(timeline),
        )

    @staticmethod
    def _timeline(
        *,
        signals,
        snapshots,
        paper_trades,
        pipeline_status,
        eod,
    ):
        events = []

        for row in snapshots[:100]:
            ts = _safe_ts(row.get("snapshot_timestamp"))
            if ts is None:
                continue
            events.append({
                "timestamp": ts.isoformat(),
                "time": ts.strftime("%H:%M:%S"),
                "event": (
                    "EOD option snapshot"
                    if row.get("collector_mode") == "EOD"
                    else "Option snapshot"
                ),
                "detail": (
                    f"Snapshot {row.get('id')} · "
                    f"Expiry {row.get('option_expiry') or '—'}"
                ),
            })

        for row in signals:
            ts = _safe_ts(row.get("confirmation_timestamp"))
            if ts is None:
                continue
            events.append({
                "timestamp": ts.isoformat(),
                "time": ts.strftime("%H:%M:%S"),
                "event": "Signal confirmed",
                "detail": (
                    f"{row.get('signal_id') or '—'} · "
                    f"{row.get('direction') or '—'}"
                ),
            })

        seen_trade_events = set()
        for row in paper_trades:
            trade_id = str(row.get("trade_id") or "")
            exit_ts = _safe_ts(row.get("exit_timestamp"))
            if not trade_id or exit_ts is None:
                continue
            key = (trade_id, exit_ts.isoformat())
            if key in seen_trade_events:
                continue
            seen_trade_events.add(key)
            points = row.get("points")
            events.append({
                "timestamp": exit_ts.isoformat(),
                "time": exit_ts.strftime("%H:%M:%S"),
                "event": "Trade model closed",
                "detail": (
                    f"{trade_id} · {row.get('exit_model') or '—'} · "
                    f"{float(points):+.2f} pts"
                    if points is not None
                    else f"{trade_id} · {row.get('exit_model') or '—'}"
                ),
            })

        if pipeline_status:
            ts = _safe_ts(pipeline_status.get("updated_at"))
            if ts is not None:
                events.append({
                    "timestamp": ts.isoformat(),
                    "time": ts.strftime("%H:%M:%S"),
                    "event": "Pipeline update",
                    "detail": (
                        f"{pipeline_status.get('status')} · "
                        f"{pipeline_status.get('message') or ''}"
                    ),
                })

        if eod:
            ts = _safe_ts(eod.get("updated_at"))
            if ts is not None:
                events.append({
                    "timestamp": ts.isoformat(),
                    "time": ts.strftime("%H:%M:%S"),
                    "event": "EOD validation",
                    "detail": (
                        f"{eod.get('status')} · "
                        f"CORE {float(eod.get('core_completeness_pct') or 0):.1f}% · "
                        f"HYBRID {float(eod.get('hybrid_completeness_pct') or 0):.1f}%"
                    ),
                })

        events.sort(
            key=lambda row: str(row["timestamp"]),
            reverse=True,
        )
        return events[:100]
