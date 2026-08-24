from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from math import isfinite
from time import monotonic
from typing import Protocol
from zoneinfo import ZoneInfo

from .calculator import DualPcrCalculator
from .models import MorningReference, OptionOiCell
from .policy import ExchangeSessionCalendar, MarketTrendResearchPolicy
from .repository import MarketTrendResearchRepository
from .source import NormalizedChainSnapshot

IST = ZoneInfo("Asia/Kolkata")


class ResearchOptionChainProvider(Protocol):
    def option_expiries(self, instrument_key: str) -> list[str]: ...
    def option_contracts(
        self,
        instrument_key: str,
        expiry_date: str | None = None,
    ) -> list[dict[str, object]]: ...
    def option_chain(self, instrument_key: str, expiry_date: str) -> list[dict[str, object]]: ...


class ResearchSpotProvider(Protocol):
    def spot(
        self,
        *,
        underlying: str,
        evaluated_at: datetime,
    ) -> tuple[float, datetime]: ...


@dataclass(frozen=True, slots=True)
class CollectionResult:
    snapshot: NormalizedChainSnapshot
    request_ms: float
    normalization_ms: float
    retained_contracts: int


def _number(value: object, *, required: bool = True) -> float | None:
    if value is None:
        if required:
            raise ValueError("RESEARCH_CHAIN_FIELD_MISSING")
        return None
    if type(value) not in (int, float):
        raise ValueError("RESEARCH_CHAIN_FIELD_INVALID")
    result = float(value)
    if not isfinite(result) or result < 0:
        raise ValueError("RESEARCH_CHAIN_FIELD_INVALID")
    return result


class UpstoxResearchChainCollector:
    """Independent spot/reference and full-chain/OI research collector."""

    def __init__(
        self,
        *,
        provider: ResearchOptionChainProvider,
        repository: MarketTrendResearchRepository,
        policy: MarketTrendResearchPolicy,
        calendar: ExchangeSessionCalendar,
        underlying: str = "NIFTY 50",
        instrument_key: str = "NSE_INDEX|Nifty 50",
        spot_provider: ResearchSpotProvider | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.policy = policy
        self.calendar = calendar
        self.underlying = underlying
        self.instrument_key = instrument_key
        self.spot_provider = spot_provider
        self._expiry_by_date: dict[date, date] = {}
        self.calculator = DualPcrCalculator(policy)

    def _expiry(self, trading_date: date) -> date:
        cached = self._expiry_by_date.get(trading_date)
        if cached is not None:
            return cached
        expiries = sorted(
            parsed
            for parsed in (
                date.fromisoformat(value)
                for value in self.provider.option_expiries(self.instrument_key)
            )
            if parsed >= trading_date
        )
        if not expiries:
            raise ValueError("EXPIRY_UNAVAILABLE")
        self._expiry_by_date[trading_date] = expiries[0]
        return expiries[0]

    @staticmethod
    def _contract_cells(
        rows: list[dict[str, object]],
        *,
        expiry: date,
        timestamp: datetime,
    ) -> tuple[OptionOiCell, ...]:
        cells: list[OptionOiCell] = []
        seen: set[str] = set()
        for row in rows:
            if type(row) is not dict:
                raise ValueError("RESEARCH_CONTRACT_ROW_MALFORMED")
            row_expiry = date.fromisoformat(str(row.get("expiry")))
            if row_expiry != expiry:
                continue
            side = str(
                row.get("instrument_type")
                or row.get("option_type")
                or row.get("option_side")
                or ""
            ).upper()
            if side not in {"CE", "PE"}:
                continue
            key = str(row.get("instrument_key") or "").strip()
            if not key or key in seen:
                raise ValueError("RESEARCH_CONTRACT_IDENTITY_INVALID")
            seen.add(key)
            strike = _number(row.get("strike_price") or row.get("strike"))
            cells.append(
                OptionOiCell(
                    instrument_key=key,
                    option_side=side,
                    strike=float(strike),
                    expiry=expiry,
                    current_oi=0.0,
                    provider_prev_oi=None,
                    source_timestamp=timestamp,
                )
            )
        if not cells:
            raise ValueError("RESEARCH_CONTRACTS_UNAVAILABLE")
        return tuple(cells)

    def capture_reference_once(
        self,
        *,
        evaluated_at: datetime | None = None,
    ) -> MorningReference | None:
        """Fix the 09:08 spot independently of option-OI availability."""
        now = evaluated_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("EVALUATED_AT_NAIVE")
        trading_date = now.astimezone(IST).date()
        raw = self.repository.load_reference(
            underlying=self.underlying,
            trading_date=trading_date,
        )
        if raw is not None:
            return None
        local_time = now.astimezone(IST).time().replace(tzinfo=None)
        if not self.policy.reference_start <= local_time <= self.policy.reference_cutoff:
            return None
        if self.spot_provider is None:
            return None
        spot, spot_timestamp = self.spot_provider.spot(
            underlying=self.underlying,
            evaluated_at=now,
        )
        if spot_timestamp.tzinfo is None or spot_timestamp.utcoffset() is None:
            raise ValueError("REFERENCE_TIMESTAMP_NAIVE")
        age = (now - spot_timestamp).total_seconds()
        if age < 0:
            raise ValueError("REFERENCE_TIMESTAMP_FUTURE")
        if age > self.policy.maximum_source_age_seconds:
            raise ValueError("REFERENCE_SPOT_STALE")
        expiry = self._expiry(trading_date)
        steps = self.policy.window_steps(trading_date, expiry, self.calendar)
        contracts = self.provider.option_contracts(
            self.instrument_key,
            expiry.isoformat(),
        )
        contract_cells = self._contract_cells(
            contracts,
            expiry=expiry,
            timestamp=spot_timestamp,
        )
        window = self.calculator.define_window(
            contract_cells,
            spot=spot,
            window_steps=steps,
        )
        reference = MorningReference(
            trading_date=trading_date,
            underlying=self.underlying,
            reference_spot=spot,
            reference_timestamp=spot_timestamp,
            expiry=expiry,
            strike_interval=window.strike_interval,
            fixed_atm=window.atm,
            window_steps=steps,
            fixed_strikes=window.strikes,
            source="UPSTOX_UNDERLYING_QUOTE",
            source_age_seconds=age,
            status="REFERENCE_FIXED",
        )
        self.repository.create_reference(reference)
        return reference

    @staticmethod
    def _normalized_cells(
        records: list[dict[str, object]],
        *,
        expiry: date,
        source_timestamp: datetime,
    ) -> tuple[float, tuple[OptionOiCell, ...]]:
        spot: float | None = None
        cells: list[OptionOiCell] = []
        seen: set[str] = set()
        for record in records:
            if type(record) is not dict:
                raise ValueError("RESEARCH_CHAIN_ROW_MALFORMED")
            strike = _number(record.get("strike_price"))
            row_spot = _number(record.get("underlying_spot_price"))
            if spot is None:
                spot = row_spot
            elif row_spot != spot:
                raise ValueError("RESEARCH_CHAIN_SPOT_CONFLICT")
            for side, field in (("CE", "call_options"), ("PE", "put_options")):
                option = record.get(field)
                if type(option) is not dict:
                    raise ValueError("RESEARCH_CHAIN_OPTION_MALFORMED")
                market = option.get("market_data")
                if type(market) is not dict:
                    raise ValueError("RESEARCH_CHAIN_MARKET_DATA_MALFORMED")
                key = str(option.get("instrument_key") or "").strip()
                if not key:
                    raise ValueError("RESEARCH_CHAIN_IDENTITY_MISSING")
                if key in seen:
                    raise ValueError("RESEARCH_CHAIN_DUPLICATE_IDENTITY")
                seen.add(key)
                cells.append(
                    OptionOiCell(
                        instrument_key=key,
                        option_side=side,
                        strike=float(strike),
                        expiry=expiry,
                        current_oi=float(_number(market.get("oi"))),
                        provider_prev_oi=_number(
                            market.get("prev_oi"), required=False
                        ),
                        source_timestamp=source_timestamp,
                    )
                )
        if spot is None or not cells:
            raise ValueError("RESEARCH_CHAIN_EMPTY")
        return float(spot), tuple(cells)

    def collect_once(self, *, evaluated_at: datetime | None = None) -> CollectionResult:
        now = evaluated_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("EVALUATED_AT_NAIVE")
        trading_date = now.astimezone(IST).date()
        expiry = self._expiry(trading_date)
        request_started = monotonic()
        records = self.provider.option_chain(
            self.instrument_key,
            expiry.isoformat(),
        )
        request_ms = (monotonic() - request_started) * 1000.0
        source_timestamp = now
        normalization_started = monotonic()
        spot, all_cells = self._normalized_cells(
            records,
            expiry=expiry,
            source_timestamp=source_timestamp,
        )
        maximum_window = self.calculator.define_window(
            all_cells,
            spot=spot,
            window_steps=5,
        )
        retained_keys = set(maximum_window.instrument_keys)
        reference = self.repository.load_reference(
            underlying=self.underlying,
            trading_date=trading_date,
        )
        if (
            reference is not None
            and date.fromisoformat(str(reference["expiry"])) == expiry
        ):
            fixed_strikes = {
                float(value) for value in reference["fixed_strikes"]
            }
            retained_keys.update(
                cell.instrument_key
                for cell in all_cells
                if cell.strike in fixed_strikes
            )
        retained = tuple(
            cell for cell in all_cells if cell.instrument_key in retained_keys
        )
        if len({cell.instrument_key for cell in retained}) != len(retained):
            raise ValueError("RESEARCH_CHAIN_DUPLICATE_IDENTITY")
        normalization_ms = (monotonic() - normalization_started) * 1000.0
        snapshot = NormalizedChainSnapshot(
            underlying=self.underlying,
            provider="UPSTOX",
            source_timestamp=source_timestamp,
            spot=spot,
            expiry=expiry,
            cells=retained,
            provider_request_ms=request_ms,
            normalization_ms=normalization_ms,
        )
        snapshot_key = "MTRS-" + sha256(
            f"{self.underlying}|{source_timestamp.isoformat()}".encode()
        ).hexdigest()[:32]
        self.repository.persist_source_snapshot(
            snapshot_key=snapshot_key,
            underlying=self.underlying,
            trading_date=trading_date,
            source_timestamp=source_timestamp,
            expiry=expiry,
            provider="UPSTOX",
            spot=spot,
            cells=retained,
            request_ms=request_ms,
            normalization_ms=normalization_ms,
        )
        return CollectionResult(
            snapshot,
            request_ms,
            normalization_ms,
            len(retained),
        )
