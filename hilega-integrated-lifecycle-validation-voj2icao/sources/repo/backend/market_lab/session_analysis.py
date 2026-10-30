"""Pure, fact-only session analysis built from canonical panel PCR history."""

from datetime import timedelta
from typing import Iterable

from .domain import (
    ForwardLookupConfig, IST, PCRHistoryRecord, PCRTrendClassification,
    PCRTrendConfig, SessionAnalysisObservation,
)
from .trends import calculate_trend


def build_session_analysis(
    records: Iterable[PCRHistoryRecord], *, underlying: str, expiry, trend_config: PCRTrendConfig,
    forward_config: ForwardLookupConfig = ForwardLookupConfig(),
) -> list[SessionAnalysisObservation]:
    panels = [record for record in records if record.record_kind == "panel"]
    by_observation: dict[int, dict[str, PCRHistoryRecord]] = {}
    for record in panels:
        by_observation.setdefault(record.observation_id, {})[record.mode] = record
    histories: dict[str, list[PCRHistoryRecord]] = {}
    for record in panels:
        histories.setdefault(record.fingerprint, []).append(record)
    for history in histories.values():
        history.sort(key=lambda record: (record.received_at, record.id or -1))
    groups = sorted(by_observation.values(), key=lambda group: next(iter(group.values())).received_at)

    def trend(record: PCRHistoryRecord | None, horizon: int):
        if record is None:
            return None, PCRTrendClassification.UNAVAILABLE
        result = calculate_trend(record, histories[record.fingerprint], horizon, trend_config)
        return result.absolute_pcr_change, result.classification

    output = []
    for group in groups:
        representative = group.get("full") or group.get("moving") or next(iter(group.values()))
        session = representative.received_at.astimezone(IST).date()
        def future(minutes: int):
            target = representative.received_at + timedelta(minutes=minutes)
            latest = target + timedelta(seconds=forward_config.timestamp_tolerance_seconds)
            candidates = [
                next(iter(candidate.values())) for candidate in groups
                if (candidate_rep := next(iter(candidate.values()))).configuration_version == representative.configuration_version
                and candidate_rep.received_at.astimezone(IST).date() == session
                and target <= candidate_rep.received_at <= latest
            ]
            return min(candidates, key=lambda item: (item.received_at, item.id or -1), default=None)
        future_records = {minutes: future(minutes) for minutes in (5, 10, 15, 30)}
        changes = {minutes: (item.underlying_spot - representative.underlying_spot if item else None) for minutes, item in future_records.items()}
        fixed5, fixed_class = trend(group.get("fixed"), 300); fixed15, _ = trend(group.get("fixed"), 900)
        moving5, moving_class = trend(group.get("moving"), 300); moving15, _ = trend(group.get("moving"), 900)
        full5, full_class = trend(group.get("full"), 300); full15, _ = trend(group.get("full"), 900)
        output.append(SessionAnalysisObservation(
            observation_id=representative.observation_id, received_at=representative.received_at,
            provider_timestamp=representative.provider_timestamp, underlying=underlying, expiry=expiry,
            calculation_fingerprint=representative.fingerprint, configuration_version=representative.configuration_version,
            underlying_spot=representative.underlying_spot,
            fixed_pcr=group.get("fixed").pcr if group.get("fixed") else None,
            moving_pcr=group.get("moving").pcr if group.get("moving") else None,
            full_pcr=group.get("full").pcr if group.get("full") else None,
            fixed_change_5m=fixed5, fixed_change_15m=fixed15, fixed_trend_5m=fixed_class,
            moving_change_5m=moving5, moving_change_15m=moving15, moving_trend_5m=moving_class,
            full_change_5m=full5, full_change_15m=full15, full_trend_5m=full_class,
            spot_plus_5m=future_records[5].underlying_spot if future_records[5] else None,
            spot_plus_10m=future_records[10].underlying_spot if future_records[10] else None,
            spot_plus_15m=future_records[15].underlying_spot if future_records[15] else None,
            spot_plus_30m=future_records[30].underlying_spot if future_records[30] else None,
            forward_change_5m=changes[5], forward_change_10m=changes[10],
            forward_change_15m=changes[15], forward_change_30m=changes[30],
        ))
    return output
