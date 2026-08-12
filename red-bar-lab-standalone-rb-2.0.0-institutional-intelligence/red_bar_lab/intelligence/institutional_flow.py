from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class InstitutionalFlowRow:
    strike: float
    option_type: str
    premium: float | None
    premium_change_pct: float | None
    oi: float | None
    oi_change_pct: float | None
    volume: float | None
    behaviour: str
    activity: str
    directional_bias: str
    confidence_pct: float
    evidence: str

    def as_dict(self) -> dict[str, object]:
        return {
            "Strike": self.strike,
            "Side": self.option_type,
            "Premium": self.premium,
            "Premium Change %": self.premium_change_pct,
            "OI": self.oi,
            "OI Change %": self.oi_change_pct,
            "Volume": self.volume,
            "OI Behaviour": self.behaviour,
            "Institutional Activity": self.activity,
            "Directional Bias": self.directional_bias,
            "Confidence %": self.confidence_pct,
            "Evidence": self.evidence,
        }


@dataclass(frozen=True)
class InstitutionalFlowSnapshot:
    snapshot_timestamp: str | None
    previous_snapshot_timestamp: str | None
    option_expiry: str | None
    rows: tuple[InstitutionalFlowRow, ...]
    bullish_flow_pct: float
    bearish_flow_pct: float
    neutral_flow_pct: float
    dominant_activity: str
    strongest_bullish: str | None
    strongest_bearish: str | None
    status: str
    reason: str


class InstitutionalOptionFlowEngine:
    """Read-only institutional option-flow classifier.

    Sprint-1 scope is intentionally observational. It derives behaviour from two
    consecutive captured option-chain snapshots and never writes execution state,
    candidate scores, committee policy or portfolio decisions.
    """

    PRICE_NOISE_PCT = 0.15
    OI_NOISE_PCT = 0.50

    @staticmethod
    def _num(value: object) -> float | None:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _pct(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None or previous == 0:
            return None
        return (current - previous) / abs(previous) * 100.0

    @staticmethod
    def _artifact(path_value: object) -> pd.DataFrame:
        if not path_value:
            return pd.DataFrame()
        try:
            path = Path(str(path_value))
            if not path.exists():
                return pd.DataFrame()
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()

    @classmethod
    def classify_oi_behaviour(cls, price_change_pct: float | None, oi_change_pct: float | None) -> str:
        if price_change_pct is None or oi_change_pct is None:
            return "UNKNOWN"
        p = 0.0 if abs(price_change_pct) < cls.PRICE_NOISE_PCT else price_change_pct
        o = 0.0 if abs(oi_change_pct) < cls.OI_NOISE_PCT else oi_change_pct
        if o > 0 and p > 0:
            return "LONG_BUILDUP"
        if o > 0 and p < 0:
            return "SHORT_BUILDUP"
        if o < 0 and p > 0:
            return "SHORT_COVERING"
        if o < 0 and p < 0:
            return "LONG_UNWINDING"
        return "NEUTRAL"

    @classmethod
    def classify_activity(cls, option_type: str, behaviour: str) -> str:
        if option_type == "CE":
            if behaviour == "LONG_BUILDUP":
                return "CALL_BUYING"
            if behaviour == "SHORT_BUILDUP":
                return "CALL_WRITING"
            if behaviour == "SHORT_COVERING":
                return "CALL_WRITER_COVERING"
            if behaviour == "LONG_UNWINDING":
                return "CALL_BUYER_UNWINDING"
        elif option_type == "PE":
            if behaviour == "LONG_BUILDUP":
                return "PUT_BUYING"
            if behaviour == "SHORT_BUILDUP":
                return "PUT_WRITING"
            if behaviour == "SHORT_COVERING":
                return "PUT_WRITER_COVERING"
            if behaviour == "LONG_UNWINDING":
                return "PUT_BUYER_UNWINDING"
        return "NO_CLEAR_ACTIVITY"

    @staticmethod
    def directional_bias(activity: str) -> str:
        bullish = {"CALL_BUYING", "PUT_WRITING", "PUT_BUYER_UNWINDING", "CALL_WRITER_COVERING"}
        bearish = {"PUT_BUYING", "CALL_WRITING", "CALL_BUYER_UNWINDING", "PUT_WRITER_COVERING"}
        if activity in bullish:
            return "BULLISH"
        if activity in bearish:
            return "BEARISH"
        return "NEUTRAL"

    @classmethod
    def confidence(cls, price_change_pct: float | None, oi_change_pct: float | None, volume: float | None) -> float:
        if price_change_pct is None or oi_change_pct is None:
            return 0.0
        price_strength = min(35.0, abs(price_change_pct) / 2.0 * 35.0)
        oi_strength = min(45.0, abs(oi_change_pct) / 10.0 * 45.0)
        volume_strength = 0.0 if volume is None else min(20.0, max(0.0, volume) / 100000.0 * 20.0)
        return round(min(100.0, price_strength + oi_strength + volume_strength), 2)

    @classmethod
    def _side_row(cls, current: pd.Series, previous: pd.Series, side: str) -> InstitutionalFlowRow:
        prefix = "call" if side == "CE" else "put"
        strike = cls._num(current.get("strike")) or 0.0
        premium = cls._num(current.get(f"{prefix}_ltp"))
        prior_premium = cls._num(previous.get(f"{prefix}_ltp"))
        oi = cls._num(current.get(f"{prefix}_oi"))
        prior_oi = cls._num(previous.get(f"{prefix}_oi"))
        volume = cls._num(current.get(f"{prefix}_volume"))
        price_pct = cls._pct(premium, prior_premium)
        oi_pct = cls._pct(oi, prior_oi)
        behaviour = cls.classify_oi_behaviour(price_pct, oi_pct)
        activity = cls.classify_activity(side, behaviour)
        bias = cls.directional_bias(activity)
        confidence = cls.confidence(price_pct, oi_pct, volume)
        evidence = (
            f"Premium {price_pct:+.2f}%" if price_pct is not None else "Premium change unavailable"
        ) + "; " + (
            f"OI {oi_pct:+.2f}%" if oi_pct is not None else "OI change unavailable"
        )
        return InstitutionalFlowRow(
            strike=round(strike, 2), option_type=side, premium=premium,
            premium_change_pct=round(price_pct, 3) if price_pct is not None else None,
            oi=oi, oi_change_pct=round(oi_pct, 3) if oi_pct is not None else None,
            volume=volume, behaviour=behaviour, activity=activity,
            directional_bias=bias, confidence_pct=confidence, evidence=evidence,
        )

    @classmethod
    def evaluate_frames(
        cls,
        current: pd.DataFrame,
        previous: pd.DataFrame,
        *,
        snapshot_timestamp: str | None = None,
        previous_snapshot_timestamp: str | None = None,
        option_expiry: str | None = None,
    ) -> InstitutionalFlowSnapshot:
        if current is None or previous is None or current.empty or previous.empty:
            return InstitutionalFlowSnapshot(snapshot_timestamp, previous_snapshot_timestamp, option_expiry, (), 0.0, 0.0, 100.0,
                "INSUFFICIENT_DATA", None, None, "WAITING", "Two non-empty option-chain snapshots are required.")
        if "strike" not in current.columns or "strike" not in previous.columns:
            return InstitutionalFlowSnapshot(snapshot_timestamp, previous_snapshot_timestamp, option_expiry, (), 0.0, 0.0, 100.0,
                "INSUFFICIENT_DATA", None, None, "WAITING", "Option-chain snapshots do not contain strike data.")

        cur = current.copy(); prev = previous.copy()
        cur["strike"] = pd.to_numeric(cur["strike"], errors="coerce")
        prev["strike"] = pd.to_numeric(prev["strike"], errors="coerce")
        prev_by_strike = {float(r["strike"]): r for _, r in prev.dropna(subset=["strike"]).iterrows()}
        rows: list[InstitutionalFlowRow] = []
        for _, current_row in cur.dropna(subset=["strike"]).iterrows():
            prior = prev_by_strike.get(float(current_row["strike"]))
            if prior is None:
                continue
            rows.append(cls._side_row(current_row, prior, "CE"))
            rows.append(cls._side_row(current_row, prior, "PE"))

        if not rows:
            return InstitutionalFlowSnapshot(snapshot_timestamp, previous_snapshot_timestamp, option_expiry, (), 0.0, 0.0, 100.0,
                "INSUFFICIENT_DATA", None, None, "WAITING", "No strikes overlapped between consecutive snapshots.")

        weighted = {"BULLISH": 0.0, "BEARISH": 0.0, "NEUTRAL": 0.0}
        for row in rows:
            weighted[row.directional_bias] += max(1.0, row.confidence_pct)
        total = sum(weighted.values()) or 1.0
        bullish = round(weighted["BULLISH"] / total * 100.0, 2)
        bearish = round(weighted["BEARISH"] / total * 100.0, 2)
        neutral = round(max(0.0, 100.0 - bullish - bearish), 2)
        activities: dict[str, float] = {}
        for row in rows:
            activities[row.activity] = activities.get(row.activity, 0.0) + max(1.0, row.confidence_pct)
        dominant = max(activities, key=activities.get) if activities else "NO_CLEAR_ACTIVITY"
        bullish_rows = sorted((r for r in rows if r.directional_bias == "BULLISH"), key=lambda r: r.confidence_pct, reverse=True)
        bearish_rows = sorted((r for r in rows if r.directional_bias == "BEARISH"), key=lambda r: r.confidence_pct, reverse=True)
        return InstitutionalFlowSnapshot(
            snapshot_timestamp, previous_snapshot_timestamp, option_expiry, tuple(rows), bullish, bearish, neutral, dominant,
            f"{bullish_rows[0].strike:.0f} {bullish_rows[0].option_type}" if bullish_rows else None,
            f"{bearish_rows[0].strike:.0f} {bearish_rows[0].option_type}" if bearish_rows else None,
            "READY", f"Compared {len(rows)//2} strikes across two consecutive captured snapshots.",
        )


class InstitutionalFlowService:
    """Read-only adapter over persisted option-chain snapshots."""

    def __init__(self, database) -> None:
        self.database = database

    def latest(self, instrument_key: str, trading_date: str) -> InstitutionalFlowSnapshot:
        history = self.database.read_option_chain_history(instrument_key, trading_date, trading_date, limit=2000)
        usable = []
        for meta in history:
            if str(meta.get("collector_mode") or "").upper() != "ONLINE":
                continue
            frame = InstitutionalOptionFlowEngine._artifact(meta.get("chain_artifact_path"))
            if frame.empty:
                continue
            ts = pd.Timestamp(meta.get("snapshot_timestamp"))
            usable.append((ts, meta, frame))
        usable.sort(key=lambda item: item[0])
        if len(usable) < 2:
            return InstitutionalFlowSnapshot(None, None, None, (), 0.0, 0.0, 100.0, "INSUFFICIENT_DATA", None, None,
                "WAITING", "At least two ONLINE option-chain snapshots are required for institutional flow classification.")
        previous_ts, previous_meta, previous = usable[-2]
        current_ts, current_meta, current = usable[-1]
        return InstitutionalOptionFlowEngine.evaluate_frames(
            current, previous,
            snapshot_timestamp=current_ts.isoformat(), previous_snapshot_timestamp=previous_ts.isoformat(),
            option_expiry=str(current_meta.get("option_expiry") or "") or None,
        )
