"""Read-only factual inventory of already recorded IST sessions."""

from collections import Counter, defaultdict
from statistics import median

from sqlalchemy import select

from .domain import (
    Evaluation, PCRConfig, RecordedSessionInventoryConfig, RecordedSessionInventoryReport,
    RecordedSessionInventoryRow, Snapshot,
)
from .storage import Configuration, Observation, PCRHistorySnapshot, session_analysis_results


def recorded_session_inventory(session, config_id=None, inventory_config=RecordedSessionInventoryConfig()):
    if config_id is not None and session.get(Configuration, config_id) is None:
        raise ValueError("Configuration not found")
    query = select(Observation)
    if config_id is not None:
        query = query.where(Observation.config_id == config_id)
    stored = session.scalars(query.order_by(Observation.config_id, Observation.id)).all()
    grouped = defaultdict(list)
    for row in stored:
        grouped[(row.config_id, row.session_date)].append(row)
    analysis_cache = {}
    result = []

    def percentage(count, total):
        return count / total * 100 if total else None

    for (current_config_id, session_date), rows in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        config = PCRConfig.model_validate(session.get(Configuration, current_config_id).payload)
        parsed = []
        parseable = 0
        for row in rows:
            try:
                parsed.append((row, Snapshot.model_validate(row.snapshot), Evaluation.model_validate(row.evaluation)))
                parseable += 1
            except ValueError:
                parsed.append((row, None, None))
        id_times = [snapshot.received_at for _, snapshot, _ in parsed if snapshot is not None]
        out_of_order = sum(later < earlier for earlier, later in zip(id_times, id_times[1:]))
        duplicate_count = sum(count - 1 for count in Counter(id_times).values() if count > 1)
        chronological = sorted((item for item in parsed if item[1] is not None), key=lambda item: (item[1].received_at, item[0].id))
        intervals = [(right[1].received_at - left[1].received_at).total_seconds() for left, right in zip(chronological, chronological[1:])]
        spot_count = sum(snapshot is not None and snapshot.spot > 0 for _, snapshot, _ in parsed)
        panel_counts = {mode: sum(evaluation is not None and next((value.pcr for value in evaluation.results if value.mode == mode), None) is not None for _, _, evaluation in parsed) for mode in ("fixed", "moving", "full")}
        anchors = [evaluation.anchor.captured_at for _, _, evaluation in parsed if evaluation is not None and evaluation.anchor is not None]
        missed = any(evaluation is not None and evaluation.anchor_status == "missed" for _, _, evaluation in parsed)
        anchor_status = "CAPTURED" if anchors else "MISSED" if missed else "UNAVAILABLE"
        current_complete = previous_complete = contract_complete = 0
        history_complete = panel_history_complete = 0
        for row, snapshot, _ in parsed:
            if snapshot is None:
                continue
            catalog_keys = {contract.key for contract in snapshot.catalog}
            quote_by_key = {quote.key: quote for quote in snapshot.quotes}
            current_complete += bool(catalog_keys and all(key in quote_by_key and quote_by_key[key].oi is not None for key in catalog_keys))
            previous_complete += bool(catalog_keys and all(key in quote_by_key and quote_by_key[key].prev_oi is not None for key in catalog_keys))
            sides = defaultdict(set)
            for contract in snapshot.catalog:
                sides[contract.strike].add(contract.side)
            contract_complete += bool(catalog_keys and all(value == {"CE", "PE"} for value in sides.values()) and catalog_keys <= set(quote_by_key))
            identities = {(item.record_kind, item.mode, item.strike) for item in session.scalars(select(PCRHistorySnapshot).where(PCRHistorySnapshot.observation_id == row.id)).all()}
            expected = {("panel", mode, None) for mode in ("fixed", "moving", "full")} | {("strike", "strike", strike) for strike in {contract.strike for contract in snapshot.catalog}}
            history_complete += expected <= identities
            panel_history_complete += {("panel", mode, None) for mode in ("fixed", "moving", "full")} <= identities
        if current_config_id not in analysis_cache:
            analysis_cache[current_config_id] = session_analysis_results(session, current_config_id)
        analyses = [item for item in analysis_cache[current_config_id] if str(item["received_at"])[:10] == session_date]
        forward_counts = {horizon: sum(item[f"forward_change_{horizon}m"] is not None for item in analyses) for horizon in (5, 10, 15, 30)}
        total = len(rows)
        result.append(RecordedSessionInventoryRow(
            session_date=session_date, config_id=current_config_id, configuration_version=current_config_id,
            underlying=config.underlying, expiry=config.expiry, observation_count=total,
            first_received_at=chronological[0][1].received_at, last_received_at=chronological[-1][1].received_at,
            median_interval_seconds=median(intervals) if intervals else None, maximum_interval_seconds=max(intervals) if intervals else None,
            gap_count=sum(value > config.interval_seconds * inventory_config.gap_interval_multiplier for value in intervals),
            out_of_order_count=out_of_order, duplicate_timestamp_count=duplicate_count,
            spot_available_count=spot_count, spot_availability_percentage=percentage(spot_count, total),
            fixed_available_count=panel_counts["fixed"], fixed_availability_percentage=percentage(panel_counts["fixed"], total),
            moving_available_count=panel_counts["moving"], moving_availability_percentage=percentage(panel_counts["moving"], total),
            full_available_count=panel_counts["full"], full_availability_percentage=percentage(panel_counts["full"], total),
            fixed_anchor_status=anchor_status, fixed_anchor_captured_at=min(anchors) if anchors else None,
            current_oi_complete_observation_count=current_complete, current_oi_completeness_percentage=percentage(current_complete, total),
            previous_oi_complete_observation_count=previous_complete, previous_oi_completeness_percentage=percentage(previous_complete, total),
            contract_complete_observation_count=contract_complete, contract_completeness_percentage=percentage(contract_complete, total),
            **{f"forward_{horizon}m_available_count": forward_counts[horizon] for horizon in (5, 10, 15, 30)},
            **{f"forward_{horizon}m_coverage_percentage": percentage(forward_counts[horizon], total) for horizon in (5, 10, 15, 30)},
            pcr_history_complete_observation_count=history_complete,
            pcr_history_missing_observation_count=total - history_complete,
            pcr_history_coverage_percentage=percentage(history_complete, total),
            replay_ready=parseable == total, backfill_ready=parseable == total,
            session_analysis_ready=panel_history_complete == total,
            multi_session_evidence_ready=any(forward_counts.values()),
        ))
    return RecordedSessionInventoryReport(rows=result)
