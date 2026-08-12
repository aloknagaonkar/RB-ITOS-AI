from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

IST = "Asia/Kolkata"


@dataclass(frozen=True)
class ConfidenceBucket:
    bucket: str
    signals: int
    resolved: int
    wins: int
    losses: int
    win_rate_pct: float | None

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ThresholdScenario:
    threshold_pct: float
    resolved_candidates: int
    would_take: int
    wins: int
    losses: int
    win_rate_pct: float | None
    missed_wins: int
    false_positives: int
    net_option_return_pct: float

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ReplayAccuracyReport:
    trading_date: date
    data_source: str
    expected_minutes: int
    captured_minutes: int
    missing_minutes: int
    temporal_coverage_pct: float
    longest_gap_minutes: int
    missing_ranges: tuple[str, ...]
    resolved_candidates: int
    decision_accuracy_pct: float
    taken_win_rate_pct: float | None
    missed_opportunity_rate_pct: float | None
    confidence_buckets: tuple[ConfidenceBucket, ...]
    threshold_scenarios: tuple[ThresholdScenario, ...]
    recommended_threshold_pct: float | None
    recommendation_status: str
    recommendations: tuple[str, ...]


class ReplayAccuracyService:
    """Post-decision replay quality and calibration analytics.

    This service never changes live parameters. It only consumes a completed replay
    result and historical capture metadata. Future outcome information is used only
    after the original historical decision has already been frozen.
    """

    def __init__(self, option_sync, historical, *, minimum_calibration_samples: int = 30) -> None:
        self.option_sync = option_sync
        self.historical = historical
        self.minimum_calibration_samples = int(minimum_calibration_samples)

    @staticmethod
    def _minute_set(values, *, ist: bool = True) -> set[pd.Timestamp]:
        ts = pd.to_datetime(values, errors="coerce", utc=True)
        ts = ts[ts.notna()]
        if ist:
            return {pd.Timestamp(v).tz_convert(IST).floor("min") for v in ts}
        return {pd.Timestamp(v).floor("min") for v in ts}

    @staticmethod
    def _ranges(missing: set[pd.Timestamp]) -> tuple[tuple[str, ...], int]:
        if not missing:
            return (), 0
        ordered = sorted(missing)
        ranges: list[str] = []
        start = prev = ordered[0]
        longest = 1
        run = 1
        for item in ordered[1:]:
            if item - prev == pd.Timedelta(minutes=1):
                prev = item
                run += 1
                longest = max(longest, run)
                continue
            ranges.append(ReplayAccuracyService._format_range(start, prev))
            start = prev = item
            run = 1
        ranges.append(ReplayAccuracyService._format_range(start, prev))
        return tuple(ranges), longest

    @staticmethod
    def _format_range(start: pd.Timestamp, end: pd.Timestamp) -> str:
        if start == end:
            return start.strftime("%H:%M")
        return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    def _temporal_quality(self, instrument_key: str, trading_date: date, data_source: str) -> tuple[int, int, int, float, int, tuple[str, ...]]:
        underlying = self.historical.read_day(instrument_key, trading_date, interval_minutes=1)
        expected = self._minute_set(underlying["timestamp"]) if not underlying.empty and "timestamp" in underlying.columns else set()
        if data_source == "LIVE_MARKET_CAPTURE":
            snapshots = self.option_sync._live_snapshots(instrument_key, trading_date)
            captured = {ts.floor("min") for ts, _, _ in snapshots}
        else:
            manifest = self.option_sync.store.read_manifest(instrument_key, trading_date)
            captured_sets: list[set[pd.Timestamp]] = []
            for raw in manifest.get("contracts") or []:
                if not isinstance(raw, dict):
                    continue
                key = self.option_sync._contract_key(raw)
                frame = self.option_sync.store.read_candles(instrument_key, trading_date, key)
                if frame.empty or "timestamp" not in frame.columns:
                    continue
                captured_sets.append(self._minute_set(frame["timestamp"]))
            # A minute is considered present when at least one stored option contract has data.
            captured = set().union(*captured_sets) if captured_sets else set()
        missing = expected - captured if expected else set()
        matched = len(expected & captured) if expected else len(captured)
        denominator = len(expected) if expected else len(captured)
        coverage = round(matched / denominator * 100.0, 2) if denominator else 0.0
        ranges, longest = self._ranges(missing)
        return denominator, matched, len(missing), coverage, longest, ranges

    @staticmethod
    def _bucket_rows(rows) -> tuple[ConfidenceBucket, ...]:
        specs = ((0, 59.999, "<60"), (60, 64.999, "60–64"), (65, 69.999, "65–69"),
                 (70, 74.999, "70–74"), (75, 79.999, "75–79"), (80, 1000, "80+"))
        result = []
        for low, high, label in specs:
            items = [r for r in rows if low <= float(r.primary_confidence_pct) <= high]
            resolved = [r for r in items if r.outcome_result in {"WIN", "LOSS"}]
            wins = sum(r.outcome_result == "WIN" for r in resolved)
            losses = sum(r.outcome_result == "LOSS" for r in resolved)
            rate = round(wins / len(resolved) * 100.0, 2) if resolved else None
            result.append(ConfidenceBucket(label, len(items), len(resolved), wins, losses, rate))
        return tuple(result)

    @staticmethod
    def _scenario(rows, threshold: float) -> ThresholdScenario:
        # Confidence-only counterfactual. Hard market-session blocks stay excluded.
        candidates = [r for r in rows if r.candidate_symbol and not str(r.blocker).startswith("MARKET_SESSION_")
                      and r.outcome_result in {"WIN", "LOSS"}]
        takes = [r for r in candidates if float(r.primary_confidence_pct) >= threshold and float(r.expectancy_pct) > 0]
        wins = sum(r.outcome_result == "WIN" for r in takes)
        losses = sum(r.outcome_result == "LOSS" for r in takes)
        missed = sum(r.outcome_result == "WIN" and r not in takes for r in candidates)
        false_pos = losses
        ret = round(sum(float(r.option_return_pct or 0.0) for r in takes), 3)
        rate = round(wins / len(takes) * 100.0, 2) if takes else None
        return ThresholdScenario(float(threshold), len(candidates), len(takes), wins, losses, rate, missed, false_pos, ret)

    def build(self, instrument_key: str, replay_result) -> ReplayAccuracyReport:
        rows = list(replay_result.rows)
        source = getattr(replay_result, "data_source", "") or (
            "LIVE_MARKET_CAPTURE" if str(replay_result.data_fidelity).startswith("LIVE_CAPTURE") else "EXPIRED_OPTION_CANDLES"
        )
        expected, captured, missing, coverage, longest, ranges = self._temporal_quality(
            instrument_key, replay_result.trading_date, source
        )
        resolved = [r for r in rows if r.outcome_result in {"WIN", "LOSS"}]
        correct = sum(r.verdict in {"CORRECT_TAKE", "CORRECT_SKIP", "CORRECT_BLOCK"} for r in resolved)
        accuracy = round(correct / len(resolved) * 100.0, 2) if resolved else 0.0
        taken = [r for r in resolved if r.execution == "WOULD_TAKE"]
        taken_wins = sum(r.outcome_result == "WIN" for r in taken)
        taken_rate = round(taken_wins / len(taken) * 100.0, 2) if taken else None
        missed = sum(r.verdict == "MISSED_OPPORTUNITY" for r in resolved)
        resolved_skips = sum(r.execution != "WOULD_TAKE" for r in resolved)
        missed_rate = round(missed / resolved_skips * 100.0, 2) if resolved_skips else None
        scenarios = tuple(self._scenario(rows, t) for t in (60.0, 65.0, 70.0, 75.0, 80.0))

        recommendations: list[str] = []
        recommended = None
        status = "INSUFFICIENT_SAMPLE"
        sample = max((s.resolved_candidates for s in scenarios), default=0)
        if sample < self.minimum_calibration_samples:
            recommendations.append(
                f"Calibration sample is {sample}; minimum is {self.minimum_calibration_samples}. Keep live threshold unchanged and replay more sessions."
            )
        else:
            current = next(s for s in scenarios if s.threshold_pct == 70.0)
            # Prefer fewer false positives, then fewer missed wins, then higher net return.
            ranked = sorted(scenarios, key=lambda s: (s.false_positives, s.missed_wins, -s.net_option_return_pct, -s.threshold_pct))
            best = ranked[0]
            if (best.false_positives < current.false_positives or best.missed_wins < current.missed_wins) and best.threshold_pct != 70.0:
                recommended = best.threshold_pct
                status = "ADVISORY_CANDIDATE"
                recommendations.append(
                    f"Advisory confidence threshold candidate: {best.threshold_pct:.0f}% versus current 70%. Validate over additional dates before promotion."
                )
            else:
                status = "KEEP_CURRENT"
                recommendations.append("Current 70% confidence gate remains competitive on this replay sample; no threshold change suggested.")
        if coverage < 80.0:
            recommendations.append(
                f"Temporal option capture coverage is {coverage:.1f}%. Treat calibration as lower-confidence until capture coverage improves."
            )
        if longest >= 5:
            recommendations.append(f"Longest option-data gap is {longest} consecutive minute(s); inspect collector continuity before relying on fine-grained entry timing.")

        return ReplayAccuracyReport(
            trading_date=replay_result.trading_date,
            data_source=source,
            expected_minutes=expected,
            captured_minutes=captured,
            missing_minutes=missing,
            temporal_coverage_pct=coverage,
            longest_gap_minutes=longest,
            missing_ranges=ranges,
            resolved_candidates=len(resolved),
            decision_accuracy_pct=accuracy,
            taken_win_rate_pct=taken_rate,
            missed_opportunity_rate_pct=missed_rate,
            confidence_buckets=self._bucket_rows(rows),
            threshold_scenarios=scenarios,
            recommended_threshold_pct=recommended,
            recommendation_status=status,
            recommendations=tuple(recommendations),
        )
