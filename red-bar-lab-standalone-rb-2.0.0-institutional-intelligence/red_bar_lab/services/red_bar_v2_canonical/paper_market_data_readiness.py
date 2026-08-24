from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from math import isclose
from typing import Protocol

from red_bar_lab.domain.red_bar_v2 import OptionSide

from .paper_market_data import (
    PaperCanaryMarketData,
    PaperMarketDataAuthenticationError,
    PaperMarketDataCorruptionError,
    PaperMarketDataDiagnosticError,
    PaperMarketDataRateLimitError,
    PaperMarketDataStaleError,
    PaperMarketDataUnavailableError,
    verify_timestamp_freshness,
)
from .paper_market_data_readiness_models import (
    ContractReadinessEvidence,
    ContractReadinessStatus,
    MarketDataReadinessDiagnostic,
    MarketDataReadinessPolicy,
    MarketDataReadinessReport,
    MarketDataReadinessStage,
    MarketDataReadinessStatus,
    build_probe_id,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


def _dominant_interval(strikes: tuple[float, ...]) -> float:
    unique = sorted(set(float(value) for value in strikes))
    if len(unique) < 3:
        raise PaperMarketDataDiagnosticError(
            stage=MarketDataReadinessStage.STRIKE_INTERVAL_DETECTION,
            reason_code="AMBIGUOUS_STRIKE_INTERVAL",
            rejected_field="strike_interval",
            unique_strike_count=len(unique),
        )
    differences = [round(unique[index + 1] - unique[index], 8) for index in range(len(unique) - 1)]
    positive = [value for value in differences if value > 0]
    counts = Counter(positive)
    if not counts:
        raise PaperMarketDataDiagnosticError(
            stage=MarketDataReadinessStage.STRIKE_INTERVAL_DETECTION,
            reason_code="AMBIGUOUS_STRIKE_INTERVAL",
            rejected_field="strike_interval",
            unique_strike_count=len(unique),
        )
    highest = max(counts.values())
    modes = [value for value, count in counts.items() if count == highest]
    if len(modes) != 1 or highest < 2:
        raise PaperMarketDataDiagnosticError(
            stage=MarketDataReadinessStage.STRIKE_INTERVAL_DETECTION,
            reason_code="AMBIGUOUS_STRIKE_INTERVAL",
            rejected_field="strike_interval",
            unique_strike_count=len(unique),
        )
    return modes[0]


def _nearest_atm(strikes: tuple[float, ...], spot: float) -> float:
    if not strikes:
        raise PaperMarketDataDiagnosticError(
            stage=MarketDataReadinessStage.ATM_WINDOW_CONSTRUCTION,
            reason_code="CHAIN_COVERAGE_INCOMPLETE",
            rejected_field="target_window",
            unique_strike_count=0,
        )
    return min(set(float(value) for value in strikes), key=lambda value: (abs(value - spot), value))


def _moneyness(side: OptionSide, distance_steps: int) -> str:
    if distance_steps == 0:
        return "ATM"
    if side is OptionSide.CE:
        return "ITM" if distance_steps < 0 else "OTM"
    return "OTM" if distance_steps < 0 else "ITM"


class PaperMarketDataReadinessService:
    def __init__(self, *, market_data: PaperCanaryMarketData, policy: MarketDataReadinessPolicy, clock: Clock) -> None:
        self.market_data = market_data
        self.policy = policy
        self.clock = clock
        if policy.strike_steps != 4:
            raise ValueError("readiness strike_steps must be exactly 4")
        if policy.min_ce_coverage != 9 or policy.min_pe_coverage != 9:
            raise ValueError("readiness CE and PE coverage must each be exactly 9")

    def _diagnostic(self, reason: str, component: str, **counts) -> MarketDataReadinessDiagnostic:
        return MarketDataReadinessDiagnostic(reason_code=reason, source_component=component, **counts)

    def _report(
        self,
        *,
        evaluated_at: datetime,
        underlying: str,
        status: MarketDataReadinessStatus,
        reason: str,
        stage: MarketDataReadinessStage,
        diagnostic: MarketDataReadinessDiagnostic | None = None,
        underlying_key: str | None = None,
        spot: float | None = None,
        spot_timestamp: datetime | None = None,
        expiry=None,
        interval: float | None = None,
        atm: float | None = None,
        contracts=(),
    ) -> MarketDataReadinessReport:
        evidence = tuple(contracts)
        expected = 18 if expiry is not None and atm is not None else 0
        return MarketDataReadinessReport(
            probe_id=build_probe_id(
                provider=self.market_data.provider_name,
                underlying=underlying,
                evaluated_at=evaluated_at,
                expiry=expiry,
                atm_strike=atm,
            ),
            provider=self.market_data.provider_name,
            underlying=underlying,
            underlying_instrument_key=underlying_key,
            evaluated_at=evaluated_at,
            spot_price=spot,
            spot_timestamp=spot_timestamp,
            expiry=expiry,
            strike_interval=interval,
            atm_strike=atm,
            expected_contract_count=expected,
            observed_contract_count=len(evidence),
            ready_contract_count=sum(item.status is ContractReadinessStatus.READY for item in evidence),
            ce_coverage=sum(item.option_side is OptionSide.CE for item in evidence),
            pe_coverage=sum(item.option_side is OptionSide.PE for item in evidence),
            status=status,
            reason_code=reason,
            contracts=evidence,
            failure_stage=stage,
            diagnostic=diagnostic,
        )

    def _typed_failure(self, error: PaperMarketDataDiagnosticError, *, evaluated_at: datetime, underlying: str, common: dict | None = None) -> MarketDataReadinessReport:
        return self._report(
            evaluated_at=evaluated_at,
            underlying=underlying,
            status=MarketDataReadinessStatus.DATA_CORRUPT,
            reason=error.diagnostic.reason_code,
            stage=error.stage,
            diagnostic=error.diagnostic,
            **(common or {}),
        )

    def evaluate(self, *, underlying: str) -> MarketDataReadinessReport:
        evaluated_at = self.clock.now()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("readiness clock must be timezone-aware")

        try:
            spot_quote = self.market_data.underlying_quote(underlying=underlying, evaluated_at=evaluated_at)
        except PaperMarketDataAuthenticationError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.AUTHENTICATION_FAILED, reason="AUTHENTICATION_FAILED", stage=MarketDataReadinessStage.UNDERLYING_QUOTE_COLLECTION, diagnostic=self._diagnostic("AUTHENTICATION_FAILED", "underlying_quote"))
        except PaperMarketDataRateLimitError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.RATE_LIMITED, reason="RATE_LIMITED", stage=MarketDataReadinessStage.UNDERLYING_QUOTE_COLLECTION, diagnostic=self._diagnostic("RATE_LIMITED", "underlying_quote"))
        except PaperMarketDataUnavailableError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.SPOT_UNAVAILABLE, reason="UNDERLYING_QUOTE_UNAVAILABLE", stage=MarketDataReadinessStage.UNDERLYING_QUOTE_COLLECTION, diagnostic=self._diagnostic("UNDERLYING_QUOTE_UNAVAILABLE", "underlying_quote"))
        except PaperMarketDataDiagnosticError as exc:
            return self._typed_failure(exc, evaluated_at=evaluated_at, underlying=underlying)
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="UNKNOWN_SANITIZED_FAILURE", stage=MarketDataReadinessStage.UNDERLYING_QUOTE_COLLECTION, diagnostic=self._diagnostic("UNKNOWN_SANITIZED_FAILURE", "underlying_quote", rejected_field="unknown"))

        try:
            if spot_quote.provider != self.market_data.provider_name or spot_quote.underlying != underlying:
                raise PaperMarketDataDiagnosticError(stage=MarketDataReadinessStage.UNDERLYING_QUOTE_VALIDATION, reason_code="UNDERLYING_IDENTITY_MISMATCH", rejected_field="instrument_key")
            verify_timestamp_freshness(timestamp=spot_quote.quote_timestamp, evaluated_at=evaluated_at, maximum_age_seconds=self.policy.max_quote_age_seconds)
        except PaperMarketDataStaleError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.SPOT_UNAVAILABLE, reason="UNDERLYING_TIMESTAMP_INVALID", stage=MarketDataReadinessStage.UNDERLYING_QUOTE_VALIDATION, diagnostic=self._diagnostic("UNDERLYING_TIMESTAMP_INVALID", "underlying_quote", rejected_field="quote_timestamp"))
        except PaperMarketDataDiagnosticError as exc:
            return self._typed_failure(exc, evaluated_at=evaluated_at, underlying=underlying)
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="UNDERLYING_TIMESTAMP_INVALID", stage=MarketDataReadinessStage.UNDERLYING_QUOTE_VALIDATION, diagnostic=self._diagnostic("UNDERLYING_TIMESTAMP_INVALID", "underlying_quote", rejected_field="quote_timestamp"))

        common = dict(
            underlying_key=spot_quote.instrument_key,
            spot=spot_quote.last_price,
            spot_timestamp=spot_quote.quote_timestamp,
        )
        try:
            instruments = self.market_data.option_instruments(underlying=underlying, evaluated_at=evaluated_at)
        except PaperMarketDataAuthenticationError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.AUTHENTICATION_FAILED, reason="AUTHENTICATION_FAILED", stage=MarketDataReadinessStage.OPTION_CONTRACT_COLLECTION, diagnostic=self._diagnostic("AUTHENTICATION_FAILED", "option_contracts"), **common)
        except PaperMarketDataRateLimitError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.RATE_LIMITED, reason="RATE_LIMITED", stage=MarketDataReadinessStage.OPTION_CONTRACT_COLLECTION, diagnostic=self._diagnostic("RATE_LIMITED", "option_contracts"), **common)
        except PaperMarketDataUnavailableError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.PROVIDER_UNAVAILABLE, reason="OPTION_CONTRACT_REQUEST_FAILED", stage=MarketDataReadinessStage.OPTION_CONTRACT_COLLECTION, diagnostic=self._diagnostic("OPTION_CONTRACT_REQUEST_FAILED", "option_contracts"), **common)
        except PaperMarketDataDiagnosticError as exc:
            return self._typed_failure(exc, evaluated_at=evaluated_at, underlying=underlying, common=common)
        except PaperMarketDataCorruptionError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="OPTION_CONTRACT_RESPONSE_MALFORMED", stage=MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION, diagnostic=self._diagnostic("OPTION_CONTRACT_RESPONSE_MALFORMED", "option_contracts", rejected_field="response_shape"), **common)
        except (ValueError, TypeError) as exc:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="OPTION_CONTRACT_ROW_MALFORMED", stage=MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION, diagnostic=self._diagnostic("OPTION_CONTRACT_ROW_MALFORMED", "option_contracts", rejected_field="unknown", rejected_type=type(exc).__name__), **common)

        received = len(instruments)
        ce_count = sum(item.option_side is OptionSide.CE for item in instruments)
        pe_count = sum(item.option_side is OptionSide.PE for item in instruments)
        unique_strikes = len({float(item.strike) for item in instruments})
        if not instruments:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.CHAIN_UNAVAILABLE, reason="OPTION_CONTRACT_RESPONSE_MALFORMED", stage=MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION, diagnostic=self._diagnostic("OPTION_CONTRACT_RESPONSE_MALFORMED", "option_contracts", received_count=0, normalized_count=0, rejected_count=0, ce_count=0, pe_count=0, unique_strike_count=0, rejected_field="response_shape"), **common)

        structure_counts = dict(received_count=received, normalized_count=received, rejected_count=0, ce_count=ce_count, pe_count=pe_count, unique_strike_count=unique_strikes)
        try:
            ce_expiries = {item.expiry for item in instruments if item.option_side is OptionSide.CE}
            pe_expiries = {item.expiry for item in instruments if item.option_side is OptionSide.PE}
            valid_expiries = sorted(value for value in ce_expiries & pe_expiries if value >= evaluated_at.date())
            if not valid_expiries:
                return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.CHAIN_UNAVAILABLE, reason="NO_NON_EXPIRED_COMMON_EXPIRY", stage=MarketDataReadinessStage.COMMON_EXPIRY_SELECTION, diagnostic=self._diagnostic("NO_NON_EXPIRED_COMMON_EXPIRY", "chain_structure", common_expiry_count=0, rejected_field="common_expiry", **structure_counts), **common)
            expiry = valid_expiries[0]
            expiry_items = tuple(item for item in instruments if item.expiry == expiry)
            grouped: dict[tuple[OptionSide, float], list] = defaultdict(list)
            for item in expiry_items:
                grouped[(item.option_side, float(item.strike))].append(item)
            if any(len(items) > 1 for items in grouped.values()):
                raise PaperMarketDataDiagnosticError(stage=MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION, reason_code="DUPLICATE_OPTION_CELL", source_component="chain_structure", rejected_field="duplicate_identity", common_expiry_count=len(valid_expiries), **structure_counts)
            keys = [item.instrument_key for item in expiry_items]
            if len(keys) != len(set(keys)):
                raise PaperMarketDataDiagnosticError(stage=MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION, reason_code="DUPLICATE_CONTRACT_IDENTITY", source_component="chain_structure", rejected_field="duplicate_identity", common_expiry_count=len(valid_expiries), **structure_counts)
            ce_strikes = {strike for side, strike in grouped if side is OptionSide.CE}
            pe_strikes = {strike for side, strike in grouped if side is OptionSide.PE}
            common_strikes = tuple(sorted(ce_strikes & pe_strikes))
            interval = _dominant_interval(common_strikes)
            atm = _nearest_atm(common_strikes, spot_quote.last_price)
            target_strikes = tuple(atm + interval * offset for offset in range(-4, 5))
            target_set = {round(value, 8) for value in target_strikes}
            window_common = {round(value, 8) for value in common_strikes if target_strikes[0] <= value <= target_strikes[-1]}
            if window_common - target_set:
                raise PaperMarketDataDiagnosticError(stage=MarketDataReadinessStage.ATM_WINDOW_CONSTRUCTION, reason_code="IRREGULAR_TARGET_WINDOW", source_component="chain_structure", rejected_field="target_window", common_expiry_count=len(valid_expiries), **structure_counts)
            if target_set - window_common:
                return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE, reason="CHAIN_COVERAGE_INCOMPLETE", stage=MarketDataReadinessStage.ATM_WINDOW_CONSTRUCTION, diagnostic=self._diagnostic("CHAIN_COVERAGE_INCOMPLETE", "chain_structure", rejected_field="target_window", common_expiry_count=len(valid_expiries), **structure_counts), expiry=expiry, interval=interval, atm=atm, **common)
            selected = []
            seen_keys: set[str] = set()
            for offset, strike in zip(range(-4, 5), target_strikes):
                for side in (OptionSide.CE, OptionSide.PE):
                    cell = grouped.get((side, float(strike)), [])
                    if len(cell) != 1:
                        return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE, reason="CHAIN_COVERAGE_INCOMPLETE", stage=MarketDataReadinessStage.ATM_WINDOW_CONSTRUCTION, diagnostic=self._diagnostic("CHAIN_COVERAGE_INCOMPLETE", "chain_structure", rejected_field="target_window", common_expiry_count=len(valid_expiries), **structure_counts), expiry=expiry, interval=interval, atm=atm, **common)
                    item = cell[0]
                    if item.instrument_key in seen_keys:
                        raise PaperMarketDataDiagnosticError(stage=MarketDataReadinessStage.OPTION_CONTRACT_NORMALIZATION, reason_code="DUPLICATE_CONTRACT_IDENTITY", source_component="chain_structure", rejected_field="duplicate_identity", **structure_counts)
                    seen_keys.add(item.instrument_key)
                    selected.append((item, offset))
        except PaperMarketDataDiagnosticError as exc:
            return self._typed_failure(exc, evaluated_at=evaluated_at, underlying=underlying, common=common)
        except (PaperMarketDataCorruptionError, ValueError, TypeError):
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="UNKNOWN_SANITIZED_FAILURE", stage=MarketDataReadinessStage.STRIKE_INTERVAL_DETECTION, diagnostic=self._diagnostic("UNKNOWN_SANITIZED_FAILURE", "chain_structure", rejected_field="unknown", **structure_counts), **common)

        try:
            quotes = self.market_data.quotes(instrument_keys=tuple(item.instrument_key for item, _ in selected), evaluated_at=evaluated_at)
        except PaperMarketDataAuthenticationError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.AUTHENTICATION_FAILED, reason="AUTHENTICATION_FAILED", stage=MarketDataReadinessStage.OPTION_QUOTE_COLLECTION, diagnostic=self._diagnostic("AUTHENTICATION_FAILED", "option_quotes"), expiry=expiry, interval=interval, atm=atm, **common)
        except PaperMarketDataRateLimitError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.RATE_LIMITED, reason="RATE_LIMITED", stage=MarketDataReadinessStage.OPTION_QUOTE_COLLECTION, diagnostic=self._diagnostic("RATE_LIMITED", "option_quotes"), expiry=expiry, interval=interval, atm=atm, **common)
        except PaperMarketDataStaleError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.QUOTES_STALE, reason="OPTION_QUOTE_STALE", stage=MarketDataReadinessStage.QUOTE_FRESHNESS_VALIDATION, diagnostic=self._diagnostic("OPTION_QUOTE_STALE", "option_quotes", rejected_field="quote_timestamp"), expiry=expiry, interval=interval, atm=atm, **common)
        except PaperMarketDataUnavailableError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.QUOTES_UNAVAILABLE, reason="OPTION_QUOTE_REQUEST_FAILED", stage=MarketDataReadinessStage.OPTION_QUOTE_COLLECTION, diagnostic=self._diagnostic("OPTION_QUOTE_REQUEST_FAILED", "option_quotes"), expiry=expiry, interval=interval, atm=atm, **common)
        except PaperMarketDataDiagnosticError as exc:
            return self._typed_failure(exc, evaluated_at=evaluated_at, underlying=underlying, common=common)
        except PaperMarketDataCorruptionError:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="OPTION_QUOTE_RESPONSE_MALFORMED", stage=MarketDataReadinessStage.OPTION_QUOTE_CORRELATION, diagnostic=self._diagnostic("OPTION_QUOTE_RESPONSE_MALFORMED", "option_quotes", rejected_field="response_shape"), expiry=expiry, interval=interval, atm=atm, **common)
        except (ValueError, TypeError) as exc:
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="OPTION_QUOTE_PRICE_INVALID", stage=MarketDataReadinessStage.QUOTE_QUALITY_VALIDATION, diagnostic=self._diagnostic("OPTION_QUOTE_PRICE_INVALID", "option_quotes", rejected_field="quote_price", rejected_type=type(exc).__name__), expiry=expiry, interval=interval, atm=atm, **common)

        quote_map = {quote.instrument_key: quote for quote in quotes}
        requested = {item.instrument_key for item, _ in selected}
        if len(quote_map) != len(quotes) or any(key not in requested for key in quote_map):
            return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="OPTION_QUOTE_IDENTITY_CONFLICT", stage=MarketDataReadinessStage.OPTION_QUOTE_CORRELATION, diagnostic=self._diagnostic("OPTION_QUOTE_IDENTITY_CONFLICT", "option_quotes", rejected_field="quote_identity", received_count=len(quotes), normalized_count=len(quote_map)), expiry=expiry, interval=interval, atm=atm, **common)

        evidence = []
        for item, offset in selected:
            quote = quote_map.get(item.instrument_key)
            if quote is None:
                row_status, row_reason = ContractReadinessStatus.QUOTE_MISSING, "QUOTE_MISSING"
                last = bid = ask = timestamp = spread = None
            else:
                if quote.provider != self.market_data.provider_name or quote.instrument_key != item.instrument_key:
                    return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="OPTION_QUOTE_IDENTITY_CONFLICT", stage=MarketDataReadinessStage.OPTION_QUOTE_CORRELATION, diagnostic=self._diagnostic("OPTION_QUOTE_IDENTITY_CONFLICT", "option_quotes", rejected_field="quote_identity"), expiry=expiry, interval=interval, atm=atm, **common)
                last, bid, ask, timestamp = quote.last_price, quote.bid_price, quote.ask_price, quote.quote_timestamp
                try:
                    verify_timestamp_freshness(timestamp=timestamp, evaluated_at=evaluated_at, maximum_age_seconds=self.policy.max_quote_age_seconds)
                except PaperMarketDataStaleError:
                    row_status, row_reason, spread = ContractReadinessStatus.QUOTE_STALE, "QUOTE_STALE", None
                except (PaperMarketDataCorruptionError, ValueError, TypeError):
                    return self._report(evaluated_at=evaluated_at, underlying=underlying, status=MarketDataReadinessStatus.DATA_CORRUPT, reason="OPTION_QUOTE_TIMESTAMP_INVALID", stage=MarketDataReadinessStage.QUOTE_FRESHNESS_VALIDATION, diagnostic=self._diagnostic("OPTION_QUOTE_TIMESTAMP_INVALID", "option_quotes", rejected_field="quote_timestamp"), expiry=expiry, interval=interval, atm=atm, **common)
                else:
                    if bid is None or ask is None:
                        row_status, row_reason, spread = ContractReadinessStatus.BID_ASK_MISSING, "BID_ASK_MISSING", None
                    else:
                        midpoint = (bid + ask) / 2.0
                        spread = ((ask - bid) / midpoint) * 100.0
                        if spread > self.policy.maximum_spread_percentage:
                            row_status, row_reason = ContractReadinessStatus.SPREAD_TOO_WIDE, "SPREAD_TOO_WIDE"
                        else:
                            row_status, row_reason = ContractReadinessStatus.READY, "READY"
            evidence.append(ContractReadinessEvidence(item.instrument_key, item.trading_symbol, item.option_side, item.strike, item.expiry, _moneyness(item.option_side, offset), offset, item.lot_size, last, bid, ask, spread, timestamp, row_status, row_reason))

        if any(row.status is ContractReadinessStatus.QUOTE_STALE for row in evidence):
            status, reason, stage, diagnostic = MarketDataReadinessStatus.QUOTES_STALE, "OPTION_QUOTE_STALE", MarketDataReadinessStage.QUOTE_FRESHNESS_VALIDATION, self._diagnostic("OPTION_QUOTE_STALE", "option_quotes", rejected_field="quote_timestamp")
        elif any(row.status is ContractReadinessStatus.QUOTE_MISSING for row in evidence):
            status, reason, stage, diagnostic = MarketDataReadinessStatus.QUOTES_UNAVAILABLE, "OPTION_QUOTE_REQUEST_FAILED", MarketDataReadinessStage.OPTION_QUOTE_COLLECTION, self._diagnostic("OPTION_QUOTE_REQUEST_FAILED", "option_quotes")
        elif any(row.status in {ContractReadinessStatus.BID_ASK_MISSING, ContractReadinessStatus.SPREAD_TOO_WIDE} for row in evidence):
            status, reason, stage, diagnostic = MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL, "QUOTE_QUALITY_PARTIAL", MarketDataReadinessStage.COMPLETED, None
        elif sum(row.status is ContractReadinessStatus.READY for row in evidence) == 18:
            status, reason, stage, diagnostic = MarketDataReadinessStatus.READY, "READY", MarketDataReadinessStage.COMPLETED, None
        else:
            status, reason, stage, diagnostic = MarketDataReadinessStatus.DATA_CORRUPT, "BID_ASK_INVALID", MarketDataReadinessStage.QUOTE_QUALITY_VALIDATION, self._diagnostic("BID_ASK_INVALID", "option_quotes", rejected_field="bid_ask")
        return self._report(evaluated_at=evaluated_at, underlying=underlying, status=status, reason=reason, stage=stage, diagnostic=diagnostic, expiry=expiry, interval=interval, atm=atm, contracts=evidence, **common)
