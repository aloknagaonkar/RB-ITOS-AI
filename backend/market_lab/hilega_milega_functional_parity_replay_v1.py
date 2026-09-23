from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol

from .domain import HistoricalCandle, HistoricalOptionContract, IST
from .hilega_milega_audit_report_v1 import build_audit_index
from .hilega_milega_live_shadow_v1 import HilegaMilegaLiveShadowCoordinatorV1, UNDERLYING
from .live_option_minute_source_v1 import CompletedOptionMinute

MODEL = "HILEGA_MILEGA_HISTORICAL_LIVE_FUNCTIONAL_PARITY_REPLAY_V1"


class HistoricalParityGateway(Protocol):
    def historical_candles(self, instrument_key: str, session_date: date) -> list[HistoricalCandle]: ...
    def historical_option_contracts(self, underlying: str, expiry: date) -> list[HistoricalOptionContract]: ...
    def historical_option_candles(self, instrument_key: str, session_date: date) -> list[HistoricalCandle]: ...


class HistoricalParityMarketSourcesV1:
    """Historical source adapter implementing the same source interface as live shadow.

    The coordinator is unchanged; only the source of time/data differs. This is the
    parity boundary: historical replay must not reimplement strategy/option behavior.
    """

    def __init__(self, gateway: HistoricalParityGateway, session_date: date):
        self.gateway = gateway
        self.session_date = session_date
        self._underlying = sorted(gateway.historical_candles(UNDERLYING, session_date), key=lambda x: x.timestamp)
        self._option_cache: dict[str, list[CompletedOptionMinute]] = {}

    def historical_candles(self, instrument_key: str, session_date: date):
        return self.gateway.historical_candles(instrument_key, session_date)

    def nifty_intraday_1m(self, *, now: datetime | None = None):
        if now is None:
            return list(self._underlying)
        local = now.astimezone(IST)
        return [x for x in self._underlying if x.timestamp.astimezone(IST) <= local]

    def option_contracts(self, underlying: str, expiry: date):
        return [
            {
                "instrument_key": c.instrument_key,
                "expiry": c.expiry.isoformat(),
                "strike_price": c.strike,
                "instrument_type": c.side,
                "lot_size": c.lot_size,
            }
            for c in self.gateway.historical_option_contracts(underlying, expiry)
        ]

    def option_intraday_1m(self, instrument_key: str):
        if instrument_key not in self._option_cache:
            rows = sorted(self.gateway.historical_option_candles(instrument_key, self.session_date), key=lambda x: x.timestamp)
            self._option_cache[instrument_key] = [
                CompletedOptionMinute(
                    instrument_key=instrument_key,
                    timestamp=x.timestamp,
                    open=float(x.open),
                    high=float(x.high),
                    low=float(x.low),
                    close=float(x.close),
                    volume=None if x.volume is None else float(x.volume),
                )
                for x in rows
            ]
        return list(self._option_cache[instrument_key])


def normalize_functional_audit(rows: list[dict]) -> list[dict]:
    """Strip runtime-only identity while preserving trading semantics for parity tests."""
    keep = {
        "INDICATOR_CALCULATION",
        "STRATEGY_DECISION",
        "STRATEGY_TRANSITION",
        "STRATEGY_DECISION_RESULT",
        "OPTION_CANDIDATE_SET",
        "OPTION_CANDIDATE_MARKET_SNAPSHOT",
        "OPTION_SHADOW_LIFECYCLE_START",
        "OPTION_SHADOW_LIFECYCLE_UPDATE",
        "OPTION_SHADOW_LIFECYCLE_EXIT",
        "SESSION_CUTOFF_SOURCE",
        "UNDERLYING_5M_BUILD",
    }
    out = []
    for r in rows:
        if r.get("stage") not in keep:
            continue
        out.append({
            "checkpoint": r.get("checkpoint"),
            "stage": r.get("stage"),
            "status": r.get("status"),
            "payload": r.get("payload"),
        })
    return out


class HilegaMilegaHistoricalFunctionalParityReplayV1:
    """Deterministically drive the live coordinator with historical market data.

    This intentionally reuses HilegaMilegaLiveShadowCoordinatorV1 so historical and
    live paths share strategy, candidate, snapshot, ATM±2 lifecycle, exit and audit
    semantics. Runtime wall-clock/bootstrap metadata is the only allowed difference.
    """

    def __init__(
        self,
        *,
        gateway: HistoricalParityGateway,
        session_date: date,
        option_expiry: date,
        output_root: str | Path,
        warmup_calendar_days: int = 45,
    ):
        self.session_date = session_date
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.sources = HistoricalParityMarketSourcesV1(gateway, session_date)
        self.coordinator = HilegaMilegaLiveShadowCoordinatorV1(
            market_sources=self.sources,
            step_audit_path=self.output_root / "step-audit.jsonl",
            health_path=self.output_root / "data-health.jsonl",
            cache_root=self.output_root / "underlying-cache",
            warmup_calendar_days=warmup_calendar_days,
            option_expiry=option_expiry,
            option_candidate_wings=2,
            option_strike_step=50.0,
        )

    def run(self) -> dict:
        # First tick bootstrap only; subsequent minute ticks reproduce live cadence.
        now = datetime.combine(self.session_date, time(9, 15, 30), tzinfo=IST)
        end = datetime.combine(self.session_date, time(15, 0, 30), tzinfo=IST)
        processed = 0
        while now <= end:
            result = self.coordinator.process(now)
            if result.get("status") == "PROCESSED":
                processed += 1
            now += timedelta(minutes=1)

        ok, issue = self.coordinator.step_audit.verify_chain()
        rows = self.coordinator.step_audit.read_all()
        reports = build_audit_index(rows, mode="HISTORICAL_FUNCTIONAL_PARITY", chain_ok=ok, chain_issue=issue)
        import json
        (self.output_root / "detailed-audit-report.json").write_text(json.dumps(reports, indent=2, default=str) + "\n", encoding="utf-8")
        return {
            "model": MODEL,
            "session_date": self.session_date.isoformat(),
            "processed_5m_bars": processed,
            "audit_chain_ok": ok,
            "audit_chain_issue": issue,
            "audit_reports": len(reports),
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
        }
