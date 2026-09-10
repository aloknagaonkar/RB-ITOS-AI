from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

IST = ZoneInfo("Asia/Kolkata")
ENGINE_VERSION = "pcr-1.1.0"


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

    @model_validator(mode="after")
    def session_anchor(self):
        if not "09:15" <= self.anchor_time < "15:30":
            raise ValueError("Anchor must be within 09:15–15:30 IST")
        return self


class Contract(Model):
    key: str
    strike: float = Field(gt=0)
    side: Literal["CE", "PE"]


class Quote(Model):
    key: str
    oi: int | None = Field(default=None, ge=0)
    prev_oi: int | None = Field(default=None, ge=0)


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


def in_session(at: datetime) -> bool:
    local = at.astimezone(IST)
    return local.weekday() < 5 and time(9, 15) <= local.time() < time(15, 30)


def evaluate(snapshot: Snapshot, config: PCRConfig, anchor: Anchor | None = None) -> Evaluation:
    """Pure calculation using recorded times, never the replay machine's clock."""
    local = snapshot.received_at.astimezone(IST)
    issues: list[str] = []
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
        if age < -2:
            issues.append("spot_timestamp_in_future")
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
