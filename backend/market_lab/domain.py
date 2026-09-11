import hashlib
import json
from datetime import date, datetime, time
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

IST = ZoneInfo("Asia/Kolkata")
ENGINE_VERSION = "pcr-1.2.0"


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class PCRConfig(Model):
    name: str = Field(default="NIFTY PCR comparison", min_length=1, max_length=80)
    provider: Literal["demo", "upstox"] = "demo"
    underlying: str = Field(default="NSE_INDEX|Nifty 50", min_length=3, max_length=100)
    expiry: date
    wings: int = Field(default=5, ge=0, le=50)
    anchor_time: str = Field(default="09:20", pattern=r"^(09|1[0-5]):[0-5][0-9]$")
    anchor_tolerance_seconds: int = Field(default=120, ge=0, le=1800)
    interval_seconds: int = Field(default=60, ge=15, le=3600)
    max_quote_age_seconds: int = Field(default=30, ge=1, le=300)
    max_collection_seconds: int = Field(default=20, ge=1, le=120)
    trend_flat_threshold: float = Field(default=0.01, ge=0, le=10)
    trend_timestamp_tolerance_seconds: int = Field(default=60, ge=0, le=300)

    @model_validator(mode="after")
    def session_anchor(self):
        if not "09:15" <= self.anchor_time < "15:30":
            raise ValueError("Anchor must be within 09:15–15:30 IST")
        return self

    def trend_fingerprint(self, mode: str, strike: float | None = None, fixed_atm: float | None = None) -> str:
        """Stable PCR-series identity; unrelated configuration edits do not reset trend history."""
        value: dict[str, object] = {
            "engine": ENGINE_VERSION, "provider": self.provider, "underlying": self.underlying,
            "expiry": self.expiry.isoformat(), "mode": mode, "strike": strike,
        }
        if mode == "fixed":
            value.update({"wings": self.wings, "anchor_time": self.anchor_time, "fixed_atm": fixed_atm})
        elif mode == "moving":
            value["wings"] = self.wings
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def evidence_compatibility_fingerprint(self) -> str:
        """Semantic PCR identity across config versions and rolling selected expiries.

        Excludes name, expiry, collection cadence and freshness limits. Includes all
        fields that affect panel construction or trend classification.
        """
        value = {
            "engine": ENGINE_VERSION, "provider": self.provider, "underlying": self.underlying,
            "wings": self.wings, "anchor_time": self.anchor_time,
            "trend_flat_threshold": self.trend_flat_threshold,
            "trend_timestamp_tolerance_seconds": self.trend_timestamp_tolerance_seconds,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def fixed_anchor_compatibility_fingerprint(self) -> str:
        """Identity for reusing an exact captured Fixed basket within one session."""
        value = {
            "engine": ENGINE_VERSION,
            "provider": self.provider,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "wings": self.wings,
            "anchor_time": self.anchor_time,
            "anchor_tolerance_seconds": self.anchor_tolerance_seconds,
            "max_quote_age_seconds": self.max_quote_age_seconds,
            "max_collection_seconds": self.max_collection_seconds,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Contract(Model):
    key: str
    strike: float = Field(gt=0)
    side: Literal["CE", "PE"]


class Quote(Model):
    key: str
    oi: int | None = Field(default=None, ge=0)
    prev_oi: int | None = Field(default=None, ge=0)
    ltp: float | None = Field(default=None, ge=0)
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0)
    quote_timestamp: AwareDatetime | None = None


class Snapshot(Model):
    provider: Literal["demo", "upstox"]
    underlying: str
    expiry: date
    started_at: AwareDatetime
    received_at: AwareDatetime
    spot: float = Field(gt=0)
    spot_feed_at: AwareDatetime | None
    oi_source_at: AwareDatetime | None = None
    oi_unit: str = "provider_reported"
    catalog: list[Contract]
    quotes: list[Quote]
    raw: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent_catalog(self):
        if self.received_at < self.started_at:
            raise ValueError("Receipt precedes request")
        keys = [c.key for c in self.catalog]
        identities = [(c.strike, c.side) for c in self.catalog]
        if not keys or len(set(keys)) != len(keys) or len(set(identities)) != len(identities):
            raise ValueError("Empty or duplicate contract catalog")
        quote_keys = [q.key for q in self.quotes]
        if len(set(quote_keys)) != len(quote_keys) or not set(quote_keys) <= set(keys):
            raise ValueError("Duplicate or unrecognized quote contract")
        return self


class Anchor(Model):
    session: date
    provider: str
    underlying: str
    expiry: date
    captured_at: AwareDatetime
    spot: float
    atm: float
    contracts: list[Contract]


class PCRResult(Model):
    mode: Literal["fixed", "moving", "full"]
    atm: float | None = None
    strikes: list[float] = Field(default_factory=list)
    contract_keys: list[str] = Field(default_factory=list)
    expected: int = 0
    received: int = 0
    put_oi: int = 0
    call_oi: int = 0
    put_prev_oi: int | None = None
    call_prev_oi: int | None = None
    put_change_oi: int | None = None
    call_change_oi: int | None = None
    put_change_pct: float | None = None
    call_change_pct: float | None = None
    pcr: float | None = None
    issues: list[str] = Field(default_factory=list)


class Evaluation(Model):
    engine_version: str = ENGINE_VERSION
    observed_at: AwareDatetime
    anchor_status: str
    anchor: Anchor | None
    results: list[PCRResult]
    warnings: list[str]
    entry_eligible: bool = False


class PCRTrendClassification(StrEnum):
    RISING = "RISING"
    FALLING = "FALLING"
    FLAT = "FLAT"
    UNAVAILABLE = "UNAVAILABLE"


class PCRTrendConfig(Model):
    flat_threshold: float = Field(default=0.01, ge=0)
    timestamp_tolerance_seconds: int = Field(default=60, ge=0)


class PCRHistoryRecord(Model):
    id: int | None = None
    observation_id: int
    configuration_version: int
    record_kind: Literal["panel", "strike"]
    mode: Literal["fixed", "moving", "full", "strike"]
    fingerprint: str
    provider_timestamp: AwareDatetime | None = None
    received_at: AwareDatetime
    processed_at: AwareDatetime
    underlying_spot: float
    atm_reference: float | None = None
    strike: float | None = None
    call_oi: int | None = None
    put_oi: int | None = None
    previous_call_oi: int | None = None
    previous_put_oi: int | None = None
    call_oi_change: int | None = None
    put_oi_change: int | None = None
    call_oi_change_pct: float | None = None
    put_oi_change_pct: float | None = None
    strike_pcr: float | None = None
    panel_pcr: float | None = None
    panel_pcr_by_mode: dict[str, float | None] = Field(default_factory=dict)
    data_status: Literal["AVAILABLE", "UNAVAILABLE"]
    data_issues: list[str] = Field(default_factory=list)
    freshness_warnings: list[str] = Field(default_factory=list)
    engine_version: str = ENGINE_VERSION

    @property
    def pcr(self) -> float | None:
        return self.panel_pcr if self.record_kind == "panel" else self.strike_pcr


class PCRTrendResult(Model):
    record_id: int | None = None
    observation_id: int
    configuration_version: int
    record_kind: Literal["panel", "strike"]
    mode: Literal["fixed", "moving", "full", "strike"]
    strike: float | None = None
    requested_horizon_seconds: int
    current_pcr: float | None = None
    baseline_pcr: float | None = None
    absolute_pcr_change: float | None = None
    percentage_change: float | None = None
    actual_elapsed_seconds: float | None = None
    baseline_received_at: AwareDatetime | None = None
    classification: PCRTrendClassification
    status: Literal["AVAILABLE", "UNAVAILABLE"]


class StrikePositioningClassification(StrEnum):
    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    LONG_UNWINDING = "LONG_UNWINDING"
    SHORT_COVERING = "SHORT_COVERING"
    NEUTRAL = "NEUTRAL"
    UNAVAILABLE = "UNAVAILABLE"


class StrikePositioningConfig(Model):
    min_price_change_pct: float = Field(default=0.1, ge=0)
    min_oi_change_pct: float = Field(default=0.1, ge=0)
    baseline_tolerance_seconds: int = Field(default=60, ge=0, le=3600)


class StrikePositioningResult(Model):
    observation_id: int
    configuration_version: int
    received_at: AwareDatetime
    instrument_key: str
    strike: float
    side: Literal["CE", "PE"]
    horizon_seconds: Literal[300, 900, 1800]
    current_ltp: float | None = None
    baseline_ltp: float | None = None
    price_change: float | None = None
    price_change_pct: float | None = None
    current_oi: int | None = None
    baseline_oi: int | None = None
    observed_oi_change: int | None = None
    observed_oi_change_pct: float | None = None
    baseline_received_at: AwareDatetime | None = None
    actual_elapsed_seconds: float | None = None
    classification: StrikePositioningClassification
    status: Literal["AVAILABLE", "UNAVAILABLE"]


class ForwardLookupConfig(Model):
    """Forward targets accept the first in-session observation at/after target within this tolerance."""
    timestamp_tolerance_seconds: int = Field(default=30, ge=0, le=300)


class SessionAnalysisObservation(Model):
    observation_id: int
    received_at: AwareDatetime
    provider_timestamp: AwareDatetime | None = None
    underlying: str
    expiry: date
    calculation_fingerprint: str
    configuration_version: int
    underlying_spot: float
    fixed_pcr: float | None = None
    moving_pcr: float | None = None
    full_pcr: float | None = None
    fixed_change_5m: float | None = None
    fixed_change_15m: float | None = None
    fixed_trend_5m: PCRTrendClassification = PCRTrendClassification.UNAVAILABLE
    moving_change_5m: float | None = None
    moving_change_15m: float | None = None
    moving_trend_5m: PCRTrendClassification = PCRTrendClassification.UNAVAILABLE
    full_change_5m: float | None = None
    full_change_15m: float | None = None
    full_trend_5m: PCRTrendClassification = PCRTrendClassification.UNAVAILABLE
    spot_plus_5m: float | None = None
    spot_plus_10m: float | None = None
    spot_plus_15m: float | None = None
    spot_plus_30m: float | None = None
    forward_change_5m: float | None = None
    forward_change_10m: float | None = None
    forward_change_15m: float | None = None
    forward_change_30m: float | None = None


class PCRChangeBucketConfig(Model):
    large: float = Field(default=0.05, gt=0)
    medium: float = Field(default=0.02, gt=0)
    small: float = Field(default=0.01, gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if not self.small < self.medium < self.large:
            raise ValueError("PCR bucket boundaries must satisfy small < medium < large")
        return self


class ForwardOutcomeStatistics(Model):
    horizon_minutes: Literal[5, 10, 15, 30]
    observation_count: int
    available_count: int
    missing_count: int
    average_points: float | None = None
    median_points: float | None = None
    minimum_points: float | None = None
    maximum_points: float | None = None
    positive_count: int
    negative_count: int
    zero_count: int
    positive_percentage: float | None = None
    negative_percentage: float | None = None
    available_session_count: int = 0
    largest_session_available_count: int = 0
    largest_session_share_percentage: float | None = None


class PatternStatisticsGroup(Model):
    kind: Literal["single_mode_trend", "pcr_change_bucket", "moving_full_trend"]
    key: str
    mode: Literal["fixed", "moving", "full"] | None = None
    outcomes: list[ForwardOutcomeStatistics]


class PatternStatisticsReport(Model):
    calculation_fingerprint: str
    configuration_version: int
    underlying: str
    expiry: date
    observation_count: int
    distinct_session_count: int
    groups: list[PatternStatisticsGroup]


class DominantOutcome(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    BALANCED = "BALANCED"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceMaturity(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    OBSERVATIONAL = "OBSERVATIONAL"
    MULTI_SESSION = "MULTI_SESSION"


class PatternEvidenceConfig(Model):
    minimum_available_samples: int = Field(default=10, ge=1)
    minimum_sessions_for_multi_session: int = Field(default=3, ge=1)


class PatternEvidenceRow(Model):
    calculation_fingerprint: str
    evidence_compatibility_fingerprint: str | None = None
    configuration_version: int
    underlying: str
    expiry: date
    distinct_session_count: int
    available_session_count: int
    largest_session_available_count: int
    largest_session_share_percentage: float | None = None
    pattern_kind: str
    pattern_key: str
    mode: str | None = None
    horizon_minutes: int
    observation_count: int
    available_count: int
    missing_count: int
    coverage_percentage: float | None = None
    average_points: float | None = None
    median_points: float | None = None
    minimum_points: float | None = None
    maximum_points: float | None = None
    positive_count: int
    negative_count: int
    zero_count: int
    positive_percentage: float | None = None
    negative_percentage: float | None = None
    dominant_outcome: DominantOutcome
    directional_imbalance_percentage: float | None = None
    maturity: EvidenceMaturity


class PatternEvidenceReport(Model):
    calculation_fingerprint: str
    evidence_compatibility_fingerprint: str | None = None
    calculation_fingerprints: tuple[str, ...] = ()
    configuration_versions: tuple[int, ...] = ()
    expiries: tuple[date, ...] = ()
    configuration_version: int
    underlying: str
    expiry: date
    observation_count: int
    distinct_session_count: int
    rows: list[PatternEvidenceRow]


class RecordedSessionInventoryConfig(Model):
    gap_interval_multiplier: float = Field(default=1.5, ge=1)


class RecordedSessionInventoryRow(Model):
    session_date: date
    config_id: int
    configuration_version: int
    underlying: str
    expiry: date
    observation_count: int
    first_received_at: AwareDatetime
    last_received_at: AwareDatetime
    median_interval_seconds: float | None = None
    maximum_interval_seconds: float | None = None
    gap_count: int
    out_of_order_count: int
    duplicate_timestamp_count: int
    spot_available_count: int
    spot_availability_percentage: float | None = None
    fixed_available_count: int
    fixed_availability_percentage: float | None = None
    moving_available_count: int
    moving_availability_percentage: float | None = None
    full_available_count: int
    full_availability_percentage: float | None = None
    fixed_anchor_status: Literal["CAPTURED", "MISSED", "UNAVAILABLE"]
    fixed_anchor_captured_at: AwareDatetime | None = None
    current_oi_complete_observation_count: int
    current_oi_completeness_percentage: float | None = None
    previous_oi_complete_observation_count: int
    previous_oi_completeness_percentage: float | None = None
    contract_complete_observation_count: int
    contract_completeness_percentage: float | None = None
    forward_5m_available_count: int
    forward_5m_coverage_percentage: float | None = None
    forward_10m_available_count: int
    forward_10m_coverage_percentage: float | None = None
    forward_15m_available_count: int
    forward_15m_coverage_percentage: float | None = None
    forward_30m_available_count: int
    forward_30m_coverage_percentage: float | None = None
    pcr_history_complete_observation_count: int
    pcr_history_missing_observation_count: int
    pcr_history_coverage_percentage: float | None = None
    replay_ready: bool
    backfill_ready: bool
    session_analysis_ready: bool
    multi_session_evidence_ready: bool


class RecordedSessionInventoryReport(Model):
    rows: list[RecordedSessionInventoryRow]


def in_session(at: datetime) -> bool:
    local = at.astimezone(IST)
    return local.weekday() < 5 and time(9, 15) <= local.time() < time(15, 30)


def evaluate(snapshot: Snapshot, config: PCRConfig, anchor: Anchor | None = None) -> Evaluation:
    """Pure calculation using recorded times, never the replay machine's clock."""
    local = snapshot.received_at.astimezone(IST)
    issues: list[str] = []
    clock_ahead_warning = False
    if (snapshot.provider, snapshot.underlying, snapshot.expiry) != (
        config.provider,
        config.underlying,
        config.expiry,
    ):
        raise ValueError("Snapshot does not match configuration")
    if config.expiry < local.date():
        issues.append("expiry_passed")
    if not in_session(local):
        issues.append("outside_session")
    if (snapshot.received_at - snapshot.started_at).total_seconds() > config.max_collection_seconds:
        issues.append("collection_too_slow")
    if snapshot.spot_feed_at is None:
        issues.append("spot_timestamp_unknown")
    else:
        age = (snapshot.received_at - snapshot.spot_feed_at).total_seconds()
        if age < -5:
            issues.append("spot_timestamp_in_future")
        elif age < 0:
            clock_ahead_warning = True
        elif age > config.max_quote_age_seconds:
            issues.append("spot_quote_stale")
    strikes = sorted({c.strike for c in snapshot.catalog})
    atm = min(strikes, key=lambda strike: (abs(strike - snapshot.spot), strike))
    idx = strikes.index(atm)
    selected = strikes[max(0, idx - config.wings) : idx + config.wings + 1]
    range_issues = [] if len(selected) == 2 * config.wings + 1 else ["insufficient_strikes"]
    moving_contracts = [c for c in snapshot.catalog if c.strike in selected]
    if len(moving_contracts) != 2 * len(selected):
        range_issues.append("unpaired_catalog")
    if anchor and (anchor.session, anchor.provider, anchor.underlying, anchor.expiry) != (
        local.date(),
        snapshot.provider,
        snapshot.underlying,
        snapshot.expiry,
    ):
        anchor = None
    scheduled = datetime.combine(local.date(), time.fromisoformat(config.anchor_time), IST)
    delta = (local - scheduled).total_seconds()
    status = "captured" if anchor else "waiting"
    if not anchor and delta >= 0:
        if delta > config.anchor_tolerance_seconds:
            status = "missed"
        elif issues or range_issues:
            status = "waiting_for_valid_data"
        else:
            anchor = Anchor(
                session=local.date(),
                provider=snapshot.provider,
                underlying=snapshot.underlying,
                expiry=snapshot.expiry,
                captured_at=snapshot.received_at,
                spot=snapshot.spot,
                atm=atm,
                contracts=moving_contracts,
            )
            status = "captured"
    quotes = {q.key: q for q in snapshot.quotes}

    def aggregate(mode, contracts, selected_atm, extra):
        errors = [*issues, *extra]
        totals = {"CE": 0, "PE": 0}
        previous = {"CE": 0, "PE": 0}
        count = 0
        previous_count = 0
        for contract in contracts:
            quote = quotes.get(contract.key)
            if quote is not None and quote.oi is not None:
                totals[contract.side] += quote.oi
                count += 1
            if quote is not None and quote.prev_oi is not None:
                previous[contract.side] += quote.prev_oi
                previous_count += 1
        levels = sorted({c.strike for c in contracts})
        if count != len(contracts):
            errors.append("missing_or_invalid_oi")
        if len(contracts) != len(levels) * 2:
            errors.append("unpaired_catalog")
        if totals["CE"] == 0:
            errors.append("zero_call_oi")
        previous_complete = previous_count == len(contracts)
        changes = {
            side: totals[side] - previous[side] if previous_complete else None for side in ("CE", "PE")
        }

        def change_pct(side):
            if not previous_complete or previous[side] == 0:
                return None
            return changes[side] / previous[side] * 100

        errors = list(dict.fromkeys(errors))
        return PCRResult(
            mode=mode,
            atm=selected_atm,
            strikes=levels,
            contract_keys=[c.key for c in contracts],
            expected=len(contracts),
            received=count,
            put_oi=totals["PE"],
            call_oi=totals["CE"],
            put_prev_oi=previous["PE"] if previous_complete else None,
            call_prev_oi=previous["CE"] if previous_complete else None,
            put_change_oi=changes["PE"],
            call_change_oi=changes["CE"],
            put_change_pct=change_pct("PE"),
            call_change_pct=change_pct("CE"),
            pcr=totals["PE"] / totals["CE"] if not errors else None,
            issues=errors,
        )

    fixed = (
        aggregate("fixed", anchor.contracts, anchor.atm, [])
        if anchor
        else PCRResult(mode="fixed", issues=[f"anchor_{status}", *issues])
    )
    warnings = ["synthetic_data"] if snapshot.provider == "demo" else []
    if snapshot.oi_source_at is None:
        warnings.append("oi_source_timestamp_unknown")
    if clock_ahead_warning:
        warnings.append("provider_clock_ahead_within_tolerance")
    warnings.append("spot_timestamp_is_feed_time_not_field_update_proof")
    return Evaluation(
        observed_at=snapshot.received_at,
        anchor_status=status,
        anchor=anchor,
        results=[
            fixed,
            aggregate("moving", moving_contracts, atm, range_issues),
            aggregate("full", snapshot.catalog, None, []),
        ],
        warnings=warnings,
    )
