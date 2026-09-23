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

    def __init__(self, gateway: HistoricalParityGateway, session_date: date, *,
                 acquisition_today: date | None = None):
        self.gateway = gateway
        self.session_date = session_date
        # An explicit date is injectable only for deterministic tests. Production
        # uses the IST broker-date at acquisition time.
        self.acquisition_today = acquisition_today or datetime.now(IST).date()
        self._option_expiry: date | None = None
        self.underlying_source = ('UPSTOX_INTRADAY_V3' if session_date == self.acquisition_today
                                  else 'UPSTOX_HISTORICAL_V3')
        self.option_contract_source: str | None = None
        self.option_candle_sources: dict[str, str] = {}
        self.option_contract_coverage: list[dict] = []
        if self.underlying_source == 'UPSTOX_INTRADAY_V3':
            if not hasattr(gateway, 'intraday_candles'):
                raise RuntimeError('Gateway does not support explicit current-session intraday acquisition')
            raw = gateway.intraday_candles(UNDERLYING, session_date)
        else:
            raw = gateway.historical_candles(UNDERLYING, session_date)
        self._underlying = self._validate_rows(raw, UNDERLYING)
        self._option_cache: dict[str, list[CompletedOptionMinute]] = {}
        self._as_of: datetime | None = None

    def _validate_rows(self, rows, instrument_key: str):
        validated = sorted(rows, key=lambda x: x.timestamp)
        seen = set()
        for row in validated:
            if row.instrument_key != instrument_key or row.timestamp.tzinfo is None:
                raise ValueError('CANDLE_INSTRUMENT_OR_TIMEZONE_MISMATCH: ' + instrument_key)
            if row.timestamp.astimezone(IST).date() != self.session_date:
                raise ValueError('CANDLE_SESSION_DATE_MISMATCH: ' + instrument_key)
            if row.timestamp in seen:
                raise ValueError('DUPLICATE_CANDLE_TIMESTAMP: ' + instrument_key)
            seen.add(row.timestamp)
        return validated

    def historical_candles(self, instrument_key: str, session_date: date):
        # This method is called for warmup only by the live coordinator.
        return self.gateway.historical_candles(instrument_key, session_date)

    def nifty_intraday_1m(self, *, now: datetime | None = None):
        if now is None:
            return list(self._underlying)
        local = now.astimezone(IST)
        self._as_of = local
        # A completed five-minute candle is filtered again by the coordinator.
        return [x for x in self._underlying if x.timestamp.astimezone(IST) <= local]

    def option_contracts(self, underlying: str, expiry: date):
        if self._option_expiry is not None and expiry != self._option_expiry:
            raise ValueError('OPTION_EXPIRY_CHANGED_DURING_REPLAY')
        self._option_expiry = expiry
        if expiry < self.session_date:
            raise ValueError('OPTION_EXPIRY_BEFORE_SESSION')
        expired = expiry < self.acquisition_today
        self.option_contract_source = ('UPSTOX_EXPIRED_CONTRACTS_V2' if expired
                                       else 'UPSTOX_ACTIVE_CONTRACTS_V2')
        if expired:
            contracts = self.gateway.historical_option_contracts(underlying, expiry)
        else:
            if not hasattr(self.gateway, 'active_option_contracts'):
                raise RuntimeError('Gateway does not support active option contract lookup')
            contracts = self.gateway.active_option_contracts(underlying, expiry)
        if not contracts:
            raise ValueError('NO_EXACT_OPTION_CONTRACTS: ' + self.option_contract_source)
        for c in contracts:
            if c.underlying != underlying or c.expiry != expiry:
                raise ValueError('OPTION_CONTRACT_IDENTITY_MISMATCH')
        self.option_contract_coverage = [
            {'instrument_key': c.instrument_key, 'expiry': c.expiry.isoformat(),
             'strike': c.strike, 'side': c.side} for c in contracts if c.side == 'CE'
        ]
        return [
            {'instrument_key': c.instrument_key, 'expiry': c.expiry.isoformat(),
             'strike_price': c.strike, 'instrument_type': c.side, 'lot_size': c.lot_size}
            for c in contracts
        ]

    def option_intraday_1m(self, instrument_key: str):
        if instrument_key not in self._option_cache:
            if self._option_expiry is None:
                raise RuntimeError('Option expiry must be resolved before option candle acquisition')
            if instrument_key not in {x['instrument_key'] for x in self.option_contract_coverage}:
                raise ValueError('OPTION_INSTRUMENT_NOT_IN_EXACT_EXPIRY_CE_CATALOG')
            if self._option_expiry < self.acquisition_today:
                source = 'UPSTOX_EXPIRED_OPTION_CANDLES_V2'
                raw = self.gateway.historical_option_candles(instrument_key, self.session_date)
            elif self.session_date == self.acquisition_today:
                source = 'UPSTOX_INTRADAY_OPTION_V3'
                raw = self.gateway.intraday_candles(instrument_key, self.session_date)
            else:
                source = 'UPSTOX_ACTIVE_OPTION_HISTORICAL_V3'
                raw = self.gateway.active_option_historical_candles(instrument_key, self.session_date)
            rows = self._validate_rows(raw, instrument_key)
            self.option_candle_sources[instrument_key] = source
            self._option_cache[instrument_key] = [
                CompletedOptionMinute(instrument_key=instrument_key, timestamp=x.timestamp,
                                      open=float(x.open), high=float(x.high), low=float(x.low),
                                      close=float(x.close),
                                      volume=None if x.volume is None else float(x.volume))
                for x in rows
            ]
        # Only fully completed option minutes become available at the simulated time.
        if self._as_of is None:
            return []
        cutoff = self._as_of.replace(second=0, microsecond=0)
        return [x for x in self._option_cache[instrument_key] if x.timestamp.astimezone(IST) < cutoff]


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
        "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY",
        "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY",
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
        acquisition_today: date | None = None,
    ):
        self.session_date = session_date
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.sources = HistoricalParityMarketSourcesV1(gateway, session_date, acquisition_today=acquisition_today)
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
        # Guard against interpreting an empty target day as a successful warmup-only replay.
        if not self.sources._underlying:
            raise ValueError('NO_TARGET_SESSION_UNDERLYING_CANDLES')
        # First tick bootstrap only; subsequent minute ticks reproduce live cadence.
        now = datetime.combine(self.session_date, time(9, 15, 30), tzinfo=IST)
        end = datetime.combine(self.session_date, time(15, 0, 30), tzinfo=IST)
        processed = 0
        while now <= end:
            result = self.coordinator.process(now)
            if result.get("status") == "PROCESSED":
                processed += 1
            now += timedelta(minutes=1)

        if processed == 0:
            raise ValueError('ZERO_TARGET_SESSION_5M_BARS_PROCESSED')
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
